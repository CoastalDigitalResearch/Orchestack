"""Webchat connector implementation."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

from orchestack_connector.base import ConnectorBase
from orchestack_connector.message import AttachmentRef, NormalizedMessage
from orchestack_connector_webchat.config import WebchatSettings

logger = logging.getLogger(__name__)


class SessionInfo:
    """Tracks an active webchat session."""

    __slots__ = (
        "_message_timestamps",
        "agent_id",
        "authenticated_sub",
        "created_at",
        "last_active",
        "sender_display_name",
        "session_id",
        "websocket",
    )

    def __init__(
        self,
        session_id: str,
        websocket: WebSocket | None = None,
        sender_display_name: str = "Anonymous",
        authenticated_sub: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.websocket = websocket
        self.created_at = time.monotonic()
        self.last_active = time.monotonic()
        self.sender_display_name = sender_display_name
        self.authenticated_sub = authenticated_sub
        self.agent_id = agent_id
        self._message_timestamps: list[float] = []

    def touch(self) -> None:
        """Update the last-active timestamp."""
        self.last_active = time.monotonic()

    def is_expired(self, timeout_s: int) -> bool:
        """Return *True* if this session has been idle longer than *timeout_s*."""
        return (time.monotonic() - self.last_active) > timeout_s

    def check_rate_limit(self, max_per_minute: int) -> bool:
        """Return *True* if the session is within rate limits."""
        now = time.monotonic()
        cutoff = now - 60.0
        self._message_timestamps = [ts for ts in self._message_timestamps if ts > cutoff]
        if len(self._message_timestamps) >= max_per_minute:
            return False
        self._message_timestamps.append(now)
        return True


class WebchatConnector(ConnectorBase):
    """Orchestack connector for a browser-based webchat widget."""

    def __init__(
        self,
        settings: WebchatSettings,
        publish_callback: Any | None = None,
    ) -> None:
        super().__init__(connector_type="webchat", account_id="default")
        self._settings = settings
        self._publish = publish_callback
        self._sessions: dict[str, SessionInfo] = {}
        self._cleanup_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    @property
    def sessions(self) -> dict[str, SessionInfo]:
        """Read-only access to the active sessions dictionary."""
        return self._sessions

    def create_session(
        self,
        websocket: WebSocket | None = None,
        display_name: str = "Anonymous",
        authenticated_sub: str | None = None,
        agent_id: str | None = None,
    ) -> SessionInfo:
        """Create a new session and store it."""
        session_id = uuid.uuid4().hex
        session = SessionInfo(
            session_id=session_id,
            websocket=websocket,
            sender_display_name=display_name,
            authenticated_sub=authenticated_sub,
            agent_id=agent_id,
        )
        self._sessions[session_id] = session
        logger.info("Session created: %s (agent_id=%s)", session_id, agent_id)
        return session

    def get_session(self, session_id: str) -> SessionInfo | None:
        """Look up a session by ID."""
        return self._sessions.get(session_id)

    def attach_websocket(self, session_id: str, websocket: WebSocket) -> bool:
        """Attach (or re-attach) a WebSocket to an existing session."""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session.websocket = websocket
        session.touch()
        return True

    def remove_session(self, session_id: str) -> None:
        """Remove a session from the active set."""
        removed = self._sessions.pop(session_id, None)
        if removed is not None:
            logger.info("Session removed: %s", session_id)

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def handle_incoming(
        self,
        session_id: str,
        data: dict[str, Any],
    ) -> NormalizedMessage | None:
        """Process an incoming JSON message from a WebSocket client."""
        session = self._sessions.get(session_id)
        if session is None:
            logger.warning("Message from unknown session %s", session_id)
            return None

        session.touch()

        # Rate limiting.
        if not session.check_rate_limit(self._settings.rate_limit_per_minute):
            logger.warning("Rate limit exceeded for session %s", session_id)
            return None

        content: str = data.get("content", "")
        if not content or len(content) > self._settings.max_message_length:
            logger.warning(
                "Message rejected (length=%d) for session %s",
                len(content),
                session_id,
            )
            return None

        # Build attachment references if the client supplied any metadata.
        raw_attachments: list[dict[str, Any]] = data.get("attachments", [])
        attachments: list[AttachmentRef] = []
        for att in raw_attachments:
            attachments.append(
                AttachmentRef(
                    filename=att.get("filename", "unknown"),
                    content_type=att.get("content_type", "application/octet-stream"),
                    size_bytes=att.get("size_bytes", 0),
                    payload_ref=att.get("payload_ref", ""),
                )
            )

        message_id = uuid.uuid4().hex

        # Include agent_id in extra for downstream routing
        extra = data.get("extra", {})
        if session.agent_id:
            extra["agent_id"] = session.agent_id

        normalized = NormalizedMessage(
            message_id=message_id,
            connector_type=self.connector_type,
            connector_account_id=self.account_id,
            thread_id=session_id,
            sender_id=session.authenticated_sub or session_id,
            sender_display_name=session.sender_display_name,
            content=content,
            attachments=attachments,
            timestamp=datetime.now(UTC),
            reply_to=data.get("reply_to"),
            extra=extra,
        )

        # Publish to NATS with agent_id in the ingress payload
        if self._publish is not None:
            ingress_payload = json.loads(normalized.model_dump_json())
            if session.agent_id:
                ingress_payload["agent_id"] = session.agent_id
            payload_bytes = json.dumps(ingress_payload).encode()
            await self._publish("ingress.webchat.message", payload_bytes)
            logger.debug("Published ingress event for message %s", message_id)

        return normalized

    # ------------------------------------------------------------------
    # Outbound / send
    # ------------------------------------------------------------------

    async def send(self, channel: str, message: str, **kwargs: Any) -> None:
        """Send a message to a WebSocket client identified by session_id."""
        session = self._sessions.get(channel)
        if session is None:
            logger.warning("Cannot send to unknown session %s", channel)
            return

        ws = session.websocket
        if ws is None:
            logger.warning("Session %s has no active WebSocket", channel)
            return

        try:
            await ws.send_text(message)
        except Exception:
            logger.exception("Failed to send to session %s", channel)
            self.remove_session(channel)

    async def send_streaming_chunk(
        self,
        session_id: str,
        chunk: str,
        *,
        done: bool = False,
        message_id: str | None = None,
    ) -> None:
        """Send a streaming response chunk to a WebSocket client."""
        payload = json.dumps(
            {
                "type": "stream",
                "chunk": chunk,
                "done": done,
                "message_id": message_id or "",
            }
        )
        await self.send(session_id, payload)

    # ------------------------------------------------------------------
    # ConnectorBase interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start session cleanup background task."""
        logger.info("Webchat connector connecting...")
        self._cleanup_task = asyncio.create_task(self._session_cleanup_loop())

    async def listen(self) -> None:
        """No-op -- WebSocket message handling is driven by FastAPI."""

    async def map_identity(self, sender_id: str) -> dict[str, Any]:
        """Return a minimal identity mapping for *sender_id*."""
        return {
            "connector_type": self.connector_type,
            "platform_id": sender_id,
        }

    async def stop(self) -> None:
        """Shut down the connector and clean up resources."""
        logger.info("Shutting down webchat connector...")
        if self._cleanup_task is not None and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
        # Close all active WebSocket connections gracefully.
        for session_id in list(self._sessions):
            session = self._sessions.get(session_id)
            if session and session.websocket:
                with contextlib.suppress(Exception):
                    await session.websocket.close(code=1001)
        self._sessions.clear()
        await super().stop()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _session_cleanup_loop(self) -> None:
        """Periodically remove expired sessions."""
        while True:
            try:
                await asyncio.sleep(60)
                timeout = self._settings.session_timeout_s
                expired = [sid for sid, session in self._sessions.items() if session.is_expired(timeout)]
                for sid in expired:
                    session = self._sessions.get(sid)
                    if session and session.websocket:
                        with contextlib.suppress(Exception):
                            await session.websocket.close(code=1000)
                    self.remove_session(sid)
                if expired:
                    logger.info("Cleaned up %d expired sessions", len(expired))
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in session cleanup loop")
