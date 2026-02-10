"""Memory Plane service entry point."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import nats
from fastapi import FastAPI, HTTPException
from nats.aio.client import Client as NATSClient
from nats.js import JetStreamContext

from .config import settings
from .models import (
    MemoryEntry,
    MemoryType,
    PromoteRequest,
    SearchRequest,
    SearchResult,
    WriteRequest,
)
from .store import MemoryStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application state populated during lifespan
# ---------------------------------------------------------------------------

_store: MemoryStore | None = None
_nc: NATSClient | None = None
_js: JetStreamContext | None = None


def _get_store() -> MemoryStore:
    assert _store is not None, "MemoryStore not initialised"
    return _store


# ---------------------------------------------------------------------------
# NATS message handlers
# ---------------------------------------------------------------------------


async def _handle_memory_write(msg) -> None:
    """Process an inbound ``memory.write`` message."""
    try:
        payload = json.loads(msg.data.decode())
        req = WriteRequest(**payload)
        entry = MemoryEntry(
            tenant_id=req.tenant_id,
            session_id=req.session_id,
            agent_id=req.agent_id,
            content=req.content,
            memory_type=req.memory_type,
            metadata=req.metadata,
        )
        store = _get_store()
        await store.write(entry)
        logger.info("NATS memory.write processed: %s", entry.id)
    except Exception:
        logger.exception("Failed to handle memory.write message")
    finally:
        await msg.ack()


async def _handle_memory_search(msg) -> None:
    """Process an inbound ``memory.search`` message and reply."""
    try:
        payload = json.loads(msg.data.decode())
        req = SearchRequest(**payload)
        store = _get_store()
        result = await store.search(req)
        response = result.model_dump_json().encode()
        if msg.reply:
            nc = _nc
            assert nc is not None
            await nc.publish(msg.reply, response)
        logger.info("NATS memory.search processed (%d results)", result.total)
    except Exception:
        logger.exception("Failed to handle memory.search message")
    finally:
        await msg.ack()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start NATS and Postgres connections; tear them down on shutdown."""
    global _store, _nc, _js

    # -- Postgres ------------------------------------------------------------
    dsn = settings.database_url
    # asyncpg expects a Postgres DSN with the ``postgresql://`` scheme.  Some
    # configurations use ``postgres://`` which asyncpg also accepts.
    pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
    _store = MemoryStore(pool)
    await _store.ensure_schema()
    logger.info("Postgres pool ready")

    # -- NATS ----------------------------------------------------------------
    _nc = await nats.connect(settings.nats_url)
    _js = _nc.jetstream()

    # Ensure the stream exists (idempotent).
    try:
        await _js.add_stream(name="MEMORY", subjects=["memory.>"])
    except Exception:
        # Stream may already exist with different config; find_stream instead.
        try:
            await _js.find_stream_name_by_subject("memory.>")
        except Exception:
            logger.warning("Could not create or find MEMORY stream; NATS subscriptions may fail")

    # Subscribe to subjects.
    await _js.subscribe("memory.write", cb=_handle_memory_write, durable="memory-plane-write")
    await _js.subscribe("memory.search", cb=_handle_memory_search, durable="memory-plane-search")
    logger.info("NATS JetStream subscriptions active")

    yield

    # -- Teardown ------------------------------------------------------------
    if _nc and not _nc.is_closed:
        await _nc.drain()
        logger.info("NATS connection drained")
    if pool:
        await pool.close()
        logger.info("Postgres pool closed")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Orchestack Memory Plane",
    version="0.1.0",
    lifespan=lifespan,
)


# -- Health endpoints --------------------------------------------------------


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    ready = _store is not None and _nc is not None and not _nc.is_closed
    if not ready:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ok"}


# -- Memory CRUD endpoints --------------------------------------------------


@app.post("/v1/memory/write", response_model=MemoryEntry, status_code=201)
async def write_memory(req: WriteRequest):
    """Write a new memory entry."""
    entry = MemoryEntry(
        tenant_id=req.tenant_id,
        session_id=req.session_id,
        agent_id=req.agent_id,
        content=req.content,
        memory_type=req.memory_type,
        metadata=req.metadata,
    )
    store = _get_store()
    return await store.write(entry)


@app.post("/v1/memory/search", response_model=SearchResult)
async def search_memory(req: SearchRequest):
    """Search memory entries by text content."""
    store = _get_store()
    return await store.search(req)


@app.post("/v1/memory/promote", response_model=MemoryEntry)
async def promote_memory(req: PromoteRequest):
    """Promote a memory entry to a higher lifecycle tier."""
    if req.target_type not in (MemoryType.short_term, MemoryType.long_term):
        raise HTTPException(
            status_code=422,
            detail="target_type must be 'short_term' or 'long_term'",
        )
    store = _get_store()
    entry = await store.promote(req.entry_id, req.target_type)
    if entry is None:
        raise HTTPException(status_code=404, detail="entry not found")
    return entry


@app.get("/v1/memory/{entry_id}", response_model=MemoryEntry)
async def get_memory(entry_id: str):
    """Retrieve a single memory entry by ID."""
    store = _get_store()
    entry = await store.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="entry not found")
    return entry


@app.delete("/v1/memory/expired")
async def delete_expired():
    """Delete all memory entries past their expiry timestamp."""
    store = _get_store()
    count = await store.delete_expired()
    return {"deleted": count}
