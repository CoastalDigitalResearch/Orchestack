"""Base class for all connectors - enhanced with NATS, health, and heartbeat."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import signal
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import nats  # type: ignore[import-untyped]
from nats.aio.client import Client as NATSClient  # type: ignore[import-untyped]
from nats.errors import (  # type: ignore[import-untyped]
    ConnectionClosedError,
    NoServersError,
)
from nats.errors import (
    TimeoutError as NATSTimeoutError,
)

from orchestack_connector.config import ConnectorSettings
from orchestack_connector.message import NormalizedMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_envelope(msg: NormalizedMessage) -> dict[str, Any]:
    """Wrap a NormalizedMessage in an RFC-001 envelope."""
    return {
        "envelope_id": str(uuid.uuid4()),
        "version": "1.0",
        "source": f"connector.{msg.connector_type}",
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": json.loads(msg.model_dump_json()),
    }


# ---------------------------------------------------------------------------
# Minimal health HTTP server (stdlib only - no extra dep)
# ---------------------------------------------------------------------------


class _HealthServer:
    """Tiny asyncio HTTP server that responds to ``/healthz`` and ``/readyz``."""

    def __init__(self, port: int) -> None:
        self._port = port
        self._server: asyncio.AbstractServer | None = None
        self.ready = False

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle,
            "0.0.0.0",
            self._port,
        )
        logger.info("Health endpoint listening on :%d", self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            # Drain remaining headers (we don't need them).
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                if line in (b"\r\n", b"\n", b""):
                    break

            path = request_line.decode(errors="replace").split(" ")[1] if b" " in request_line else "/"

            if path == "/healthz":
                body = b'{"status":"ok"}'
                status_line = "200 OK"
            elif path == "/readyz":
                if self.ready:
                    body = b'{"status":"ready"}'
                    status_line = "200 OK"
                else:
                    body = b'{"status":"not_ready"}'
                    status_line = "503 Service Unavailable"
            else:
                body = b'{"error":"not_found"}'
                status_line = "404 Not Found"

            response = (
                f"HTTP/1.1 {status_line}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode() + body

            writer.write(response)
            await writer.drain()
        except Exception:
            logger.debug("Health handler error", exc_info=True)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()


# ---------------------------------------------------------------------------
# ConnectorBase
# ---------------------------------------------------------------------------


class ConnectorBase(ABC):
    """Abstract base class for Orchestack connectors.

    Subclasses **must** implement:

    * :meth:`connect` - set up the platform-specific connection (e.g. Discord
      bot login, Slack socket-mode, etc.).
    * :meth:`listen` - begin consuming platform events and call
      :meth:`publish_ingress` for each inbound message.
    * :meth:`send` - deliver an outbound message to the platform.
    * :meth:`map_identity` - resolve a platform sender ID to an identity dict.
    """

    def __init__(
        self,
        connector_type: str,
        account_id: str,
        settings: ConnectorSettings | None = None,
    ) -> None:
        self.connector_type = connector_type
        self.account_id = account_id
        self.settings = settings or ConnectorSettings()
        self._running = False

        # NATS
        self._nc: NATSClient | None = None
        self._egress_sub: Any = None

        # Health
        self._health = _HealthServer(self.settings.health_port)

        # Background tasks
        self._tasks: list[asyncio.Task[None]] = []

    # ------------------------------------------------------------------
    # Abstract interface (unchanged contract)
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the messaging platform."""

    @abstractmethod
    async def listen(self) -> None:
        """Listen for incoming messages and publish to NATS."""

    @abstractmethod
    async def send(self, channel: str, message: str, **kwargs: Any) -> None:
        """Send a message to the platform."""

    @abstractmethod
    async def map_identity(self, sender_id: str) -> dict[str, Any]:
        """Map platform sender ID to Orchestack identity."""

    # ------------------------------------------------------------------
    # NATS connection with exponential back-off
    # ------------------------------------------------------------------

    async def _connect_nats(self) -> None:
        """Connect to NATS with exponential back-off and jitter."""
        import random

        attempt = 0
        while self._running:
            try:
                self._nc = await nats.connect(
                    self.settings.nats_url,
                    name=f"connector.{self.connector_type}.{self.account_id}",
                    reconnected_cb=self._on_nats_reconnected,
                    disconnected_cb=self._on_nats_disconnected,
                    error_cb=self._on_nats_error,
                    max_reconnect_attempts=-1,  # let the client retry forever
                )
                logger.info("Connected to NATS at %s", self.settings.nats_url)
                return
            except (NoServersError, OSError, NATSTimeoutError) as exc:
                attempt += 1
                base = self.settings.reconnect_base_wait_s
                cap = self.settings.reconnect_max_wait_s
                wait = min(base * (2 ** (attempt - 1)), cap)
                jitter = random.uniform(0, wait * 0.25)
                total = wait + jitter
                logger.warning(
                    "NATS connect attempt %d failed (%s); retrying in %.1fs",
                    attempt,
                    exc,
                    total,
                )
                await asyncio.sleep(total)

    # NATS callbacks
    async def _on_nats_reconnected(self) -> None:
        logger.info("NATS reconnected")

    async def _on_nats_disconnected(self) -> None:
        logger.warning("NATS disconnected")

    async def _on_nats_error(self, exc: Exception) -> None:
        logger.error("NATS error: %s", exc)

    # ------------------------------------------------------------------
    # Ingress  (platform -> NATS)
    # ------------------------------------------------------------------

    async def publish_ingress(self, msg: NormalizedMessage) -> None:
        """Wrap *msg* in an RFC-001 envelope and publish to NATS.

        Subject: ``ingress.{connector_type}.message``
        """
        if self._nc is None or self._nc.is_closed:
            logger.error("Cannot publish - NATS not connected")
            return

        subject = f"ingress.{self.connector_type}.message"
        envelope = _make_envelope(msg)
        payload = json.dumps(envelope).encode()
        try:
            await self._nc.publish(subject, payload)
            logger.debug("Published ingress envelope %s to %s", envelope["envelope_id"], subject)
        except (ConnectionClosedError, NATSTimeoutError) as exc:
            logger.error("Failed to publish ingress: %s", exc)

    # ------------------------------------------------------------------
    # Egress  (NATS -> platform)
    # ------------------------------------------------------------------

    async def _subscribe_egress(self) -> None:
        """Subscribe to ``egress.{connector_type}.message`` and dispatch."""
        if self._nc is None:
            return
        subject = f"egress.{self.connector_type}.message"
        self._egress_sub = await self._nc.subscribe(subject, cb=self._handle_egress)
        logger.info("Subscribed to egress subject: %s", subject)

    async def _handle_egress(self, raw: Any) -> None:
        """Decode an egress envelope and delegate to :meth:`send`."""
        try:
            envelope = json.loads(raw.data.decode())
            payload = envelope.get("payload", {})
            channel = payload.get("thread_id", "")
            content = payload.get("content", "")
            await self.send(channel, content, envelope=envelope, payload=payload)
        except Exception:
            logger.exception("Error handling egress message")

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Publish periodic heartbeats so the control-plane knows we're alive."""
        subject = f"heartbeat.connector.{self.connector_type}"
        interval = self.settings.heartbeat_interval_s
        while self._running:
            if self._nc is not None and not self._nc.is_closed:
                beat = json.dumps(
                    {
                        "connector_type": self.connector_type,
                        "account_id": self.account_id,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                ).encode()
                try:
                    await self._nc.publish(subject, beat)
                    logger.debug("Heartbeat sent on %s", subject)
                except Exception:
                    logger.warning("Heartbeat publish failed", exc_info=True)
            await asyncio.sleep(interval)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the connector (NATS, health, heartbeat, platform)."""
        self._running = True
        logger.info(
            "Starting connector: %s/%s",
            self.connector_type,
            self.account_id,
        )

        # 1. Health endpoint
        await self._health.start()

        # 2. NATS
        await self._connect_nats()

        # 3. Egress subscription
        await self._subscribe_egress()

        # 4. Platform connect + listen
        await self.connect()

        # 5. Mark ready
        self._health.ready = True

        # 6. Background tasks (heartbeat)
        self._tasks.append(asyncio.create_task(self._heartbeat_loop()))

        # 7. Platform listen (usually long-running / blocking)
        await self.listen()

    async def stop(self) -> None:
        """Stop the connector gracefully."""
        self._running = False
        logger.info(
            "Stopping connector: %s/%s",
            self.connector_type,
            self.account_id,
        )

        self._health.ready = False

        # Cancel background tasks
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        # Drain NATS (flushes pending messages then closes)
        if self._nc is not None and not self._nc.is_closed:
            try:
                await self._nc.drain()
                logger.info("NATS connection drained")
            except Exception:
                logger.warning("Error draining NATS", exc_info=True)

        # Health server
        await self._health.stop()
        logger.info("Connector stopped")

    def run(self) -> None:
        """Convenience entry-point: run the connector until interrupted.

        Installs signal handlers for SIGINT / SIGTERM and performs a
        graceful shutdown.
        """
        loop = asyncio.new_event_loop()

        async def _main() -> None:
            stop_event = asyncio.Event()

            def _signal_handler() -> None:
                logger.info("Signal received - shutting down")
                stop_event.set()

            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _signal_handler)

            start_task = asyncio.create_task(self.start())

            # Wait for either the start task to finish or a stop signal.
            _done, _ = await asyncio.wait(
                [start_task, asyncio.create_task(stop_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )

            await self.stop()

        loop.run_until_complete(_main())
        loop.close()
