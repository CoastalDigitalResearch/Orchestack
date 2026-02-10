"""SlackConnector — Socket Mode connector for Slack workspaces."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import aiohttp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from orchestack_connector.base import ConnectorBase
from orchestack_connector.message import AttachmentRef, NormalizedMessage
from orchestack_connector_slack.config import SlackConnectorSettings

logger = logging.getLogger(__name__)

# Slack rate-limit retry defaults
_RATE_LIMIT_MAX_RETRIES = 5
_RATE_LIMIT_BASE_WAIT = 1.0  # seconds


class SlackConnector(ConnectorBase):
    """Orchestack connector that bridges a Slack workspace via Socket Mode."""

    def __init__(
        self,
        settings: SlackConnectorSettings,
        *,
        publish_callback: Any | None = None,
    ) -> None:
        super().__init__(connector_type="slack", account_id=settings.account_id)
        self.settings = settings
        self._publish_callback = publish_callback

        # Slack Bolt async application
        self._app = AsyncApp(
            token=settings.bot_token,
            signing_secret=settings.signing_secret,
        )
        self._client: AsyncWebClient = self._app.client
        self._handler: AsyncSocketModeHandler | None = None
        self._bot_user_id: str | None = None

        # Register event listeners
        self._register_listeners()

    # ------------------------------------------------------------------
    # ConnectorBase abstract method implementations
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Authenticate with Slack and resolve bot user identity."""
        auth = await self._client.auth_test()
        self._bot_user_id = auth.get("user_id")
        logger.info(
            "Slack connector authenticated as bot user %s (team %s)",
            self._bot_user_id,
            auth.get("team"),
        )

    async def listen(self) -> None:
        """Start the Socket Mode handler (runs until stopped)."""
        self._handler = AsyncSocketModeHandler(
            app=self._app,
            app_token=self.settings.app_token,
        )
        logger.info("Starting Slack Socket Mode handler")
        await self._handler.start_async()

    async def send(self, channel: str, message: str, **kwargs: Any) -> None:
        """Post a message to a Slack channel, optionally in a thread.

        Parameters
        ----------
        channel:
            Slack channel ID to post to.
        message:
            Text body of the message.
        **kwargs:
            Optional ``thread_ts`` to reply in a thread.
        """
        thread_ts: str | None = kwargs.get("thread_ts")
        await self._post_with_retry(channel, message, thread_ts=thread_ts)

    async def map_identity(self, sender_id: str) -> dict[str, Any]:
        """Resolve a Slack user ID to profile information."""
        try:
            resp = await self._client.users_info(user=sender_id)
            user = resp.get("user", {})
            profile = user.get("profile", {})
            return {
                "platform": "slack",
                "platform_user_id": sender_id,
                "display_name": profile.get("display_name") or user.get("real_name", sender_id),
                "email": profile.get("email"),
                "avatar_url": profile.get("image_192"),
            }
        except Exception:
            logger.warning("Failed to resolve identity for Slack user %s", sender_id, exc_info=True)
            return {"platform": "slack", "platform_user_id": sender_id}

    async def stop(self) -> None:
        """Shut down the Socket Mode handler and base connector."""
        if self._handler is not None:
            logger.info("Closing Slack Socket Mode handler")
            await self._handler.close_async()
        await super().stop()

    # ------------------------------------------------------------------
    # Slack event registration
    # ------------------------------------------------------------------

    def _register_listeners(self) -> None:
        """Wire up Slack Bolt event listeners."""

        @self._app.event("message")
        async def _on_message(event: dict[str, Any], say: Any) -> None:
            await self._handle_message_event(event)

        @self._app.event("app_mention")
        async def _on_app_mention(event: dict[str, Any], say: Any) -> None:
            await self._handle_message_event(event, is_mention=True)

    # ------------------------------------------------------------------
    # Core event handling
    # ------------------------------------------------------------------

    async def _handle_message_event(
        self,
        event: dict[str, Any],
        *,
        is_mention: bool = False,
    ) -> None:
        """Normalise a Slack message event and publish it."""
        # Ignore bot's own messages
        if event.get("bot_id") or event.get("user") == self._bot_user_id:
            return

        # Ignore message subtypes we don't care about (edits, deletes, etc.)
        subtype = event.get("subtype")
        if subtype and subtype not in ("file_share", "thread_broadcast"):
            return

        channel = event.get("channel", "")

        # Channel filtering
        if self.settings.channel_ids and channel not in self.settings.channel_ids:
            return

        # Thread mapping: use channel + thread_ts as thread_id, or just channel
        thread_ts = event.get("thread_ts")
        thread_id = f"{channel}:{thread_ts}" if thread_ts else channel

        # Resolve sender display name
        sender_id = event.get("user", "unknown")
        identity = await self.map_identity(sender_id)
        display_name = identity.get("display_name", sender_id)

        # Collect attachments
        attachments = await self._collect_attachments(event.get("files", []))

        # Build the reply_to reference (parent message in thread)
        reply_to: str | None = None
        if thread_ts and thread_ts != event.get("ts"):
            reply_to = f"{channel}:{thread_ts}"

        msg = NormalizedMessage(
            message_id=str(uuid4()),
            connector_type="slack",
            connector_account_id=self.account_id,
            thread_id=thread_id,
            sender_id=sender_id,
            sender_display_name=display_name,
            content=event.get("text", ""),
            attachments=attachments,
            timestamp=datetime.fromtimestamp(float(event.get("ts", 0)), tz=UTC),
            reply_to=reply_to,
            extra={
                "channel": channel,
                "ts": event.get("ts"),
                "thread_ts": thread_ts,
                "is_mention": is_mention,
            },
        )

        logger.debug("Normalised Slack message %s in thread %s", msg.message_id, thread_id)

        if self._publish_callback is not None:
            await self._publish_callback(msg)

    # ------------------------------------------------------------------
    # Attachment handling
    # ------------------------------------------------------------------

    async def _collect_attachments(
        self,
        files: list[dict[str, Any]],
    ) -> list[AttachmentRef]:
        """Download Slack file metadata into AttachmentRef objects.

        Actual binary download is deferred; we store the private URL in
        ``payload_ref`` so a downstream worker can fetch it with the bot
        token.
        """
        refs: list[AttachmentRef] = []
        for f in files:
            refs.append(
                AttachmentRef(
                    filename=f.get("name", "unknown"),
                    content_type=f.get("mimetype", "application/octet-stream"),
                    size_bytes=f.get("size", 0),
                    payload_ref=f.get("url_private", ""),
                )
            )
        return refs

    async def download_attachment(self, url: str) -> bytes:
        """Fetch an attachment binary from Slack using bot token auth."""
        headers = {"Authorization": f"Bearer {self.settings.bot_token}"}
        async with aiohttp.ClientSession() as session, session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.read()

    async def upload_file(
        self,
        channel: str,
        filename: str,
        content: bytes,
        *,
        thread_ts: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Upload a file to a Slack channel using files.upload_v2."""
        resp = await self._client.files_upload_v2(
            channel=channel,
            filename=filename,
            content=content,
            title=title or filename,
            thread_ts=thread_ts,
        )
        return resp.data  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Rate-limit-aware posting
    # ------------------------------------------------------------------

    async def _post_with_retry(
        self,
        channel: str,
        text: str,
        *,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        """Post a message with exponential back-off on rate limit errors."""
        from slack_sdk.errors import SlackApiError

        last_exc: Exception | None = None
        for attempt in range(_RATE_LIMIT_MAX_RETRIES):
            try:
                resp = await self._client.chat_postMessage(
                    channel=channel,
                    text=text,
                    thread_ts=thread_ts,
                )
                return resp.data  # type: ignore[return-value]
            except SlackApiError as exc:
                if exc.response.status_code == 429:
                    retry_after = float(exc.response.headers.get("Retry-After", _RATE_LIMIT_BASE_WAIT))
                    wait = retry_after + (_RATE_LIMIT_BASE_WAIT * attempt)
                    logger.warning(
                        "Slack rate limited (attempt %d/%d), waiting %.1fs",
                        attempt + 1,
                        _RATE_LIMIT_MAX_RETRIES,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    last_exc = exc
                else:
                    raise
        raise RuntimeError(f"Slack rate limit exceeded after {_RATE_LIMIT_MAX_RETRIES} retries") from last_exc
