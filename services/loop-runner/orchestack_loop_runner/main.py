"""Loop Runner service - Agent execution loop."""

import asyncio
import logging
from contextlib import asynccontextmanager

import nats
from fastapi import FastAPI

from orchestack_loop_runner.config import Settings
from orchestack_loop_runner.loop import AgentLoop

logger = logging.getLogger(__name__)
settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    nc = await nats.connect(settings.nats_url)
    js = nc.jetstream()

    loop = AgentLoop(js=js, settings=settings)

    sub = await js.subscribe(
        "tasks.dispatch",
        stream="STREAM_TASKS",
        durable="loop-runner",
        manual_ack=True,
    )

    async def consume():
        async for msg in sub.messages:
            try:
                await loop.handle_dispatch(msg)
            except Exception as e:
                logger.error("Failed to handle dispatch: %s", e)
                await msg.nak()

    task = asyncio.create_task(consume())

    yield {"nc": nc, "js": js}

    task.cancel()
    await nc.close()


app = FastAPI(title="Orchestack Loop Runner", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    return {"status": "ok"}
