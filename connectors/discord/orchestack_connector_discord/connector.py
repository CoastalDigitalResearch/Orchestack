"""Discord connector implementation."""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
from datetime import UTC
from typing import Any

import discord

from orchestack_connector.base import ConnectorBase
from orchestack_connector.message import AttachmentRef, NormalizedMessage
from orchestack_connector_discord.config import DiscordSettings

logger = logging.getLogger(__name__)

# Maximum attachment size (in bytes) we will download inline.  Anything larger
# is referenced but not fetched during the message normalisation step.
_MAX_INLINE_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MiB


class DiscordConnector(ConnectorBase):
    """Orchestack connector for Discord using the gateway (discord.py).

    Parameters
    ----------
    settings:
        Validated :class:`DiscordSettings` instance.
    publish_callback:
        Async callable that receives ``(subject: str, data: bytes)`` and
        publishes the payload to NATS.  Injected by the entrypoint so the
        connector itself stays transport-agnostic.
    """

    def __init__(
        self,
        settings: DiscordSettings,
        publish_callback: Any | None = None,
    ) -> None:
        super().__init__(connector_type="discord", account_id="default")
        self._settings = settings
        self._publish = publish_callback

        # Build intents -- we need MESSAGE_CONTENT to read message bodies.
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = False

        self._client = discord.Client(intents=intents)

        # Register gateway event handlers.
        self._client.event(self.on_ready)
        self._client.event(self.on_message)

    # ------------------------------------------------------------------
    # ConnectorBase interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the Discord gateway connection in the background.

        ``discord.Client.start`` is a coroutine that blocks until the client
        closes, so we launch it as an ``asyncio`` task.
        """
        logger.info("Connecting to Discord gateway...")
        self._gateway_task = asyncio.create_task(self._client.start(self._settings.bot_token))

    async def listen(self) -> None:
        """No-op -- event dispatching is handled by discord.py internally."""

    async def send(self, channel: str, message: str, **kwargs: Any) -> None:
        """Send a message to a Discord channel.

        Parameters
        ----------
        channel:
            The Discord channel ID (as a string) to send the message to.
        message:
            The text content to send.
        **kwargs:
            Optional extra arguments:
            - ``embed``: a ``dict`` that will be converted to a
              :class:`discord.Embed`.
            - ``file_bytes``: raw ``bytes`` of a file to attach.
            - ``file_name``: filename for the attachment (default
              ``"attachment"``).
        """
        channel_id = int(channel)
        target = self._client.get_channel(channel_id)

        if target is None:
            try:
                target = await self._client.fetch_channel(channel_id)
            except discord.NotFound:
                logger.error("Channel %s not found, cannot send message.", channel)
                return
            except discord.Forbidden:
                logger.error("No permission to access channel %s.", channel)
                return

        send_kwargs: dict[str, Any] = {}

        # Optional embed support.
        embed_data: dict[str, Any] | None = kwargs.get("embed")
        if embed_data is not None:
            send_kwargs["embed"] = discord.Embed.from_dict(embed_data)

        # Optional file attachment.
        file_bytes: bytes | None = kwargs.get("file_bytes")
        if file_bytes is not None:
            file_name: str = kwargs.get("file_name", "attachment")
            send_kwargs["file"] = discord.File(fp=io.BytesIO(file_bytes), filename=file_name)

        try:
            await target.send(message, **send_kwargs)  # type: ignore[union-attr]
            logger.info("Sent message to channel %s.", channel)
        except discord.Forbidden:
            logger.error("No permission to send to channel %s.", channel)
        except discord.HTTPException as exc:
            logger.error("Failed to send to channel %s: %s", channel, exc)

    async def map_identity(self, sender_id: str) -> dict[str, Any]:
        """Return a minimal identity mapping for *sender_id*."""
        return {
            "connector_type": self.connector_type,
            "platform_id": sender_id,
        }

    async def stop(self) -> None:
        """Gracefully shut down the Discord client and base class."""
        logger.info("Shutting down Discord connector...")
        await self._client.close()
        if hasattr(self, "_gateway_task") and not self._gateway_task.done():
            self._gateway_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._gateway_task
        await super().stop()

    # ------------------------------------------------------------------
    # Discord event handlers
    # ------------------------------------------------------------------

    async def on_ready(self) -> None:
        """Called when the Discord gateway handshake completes."""
        assert self._client.user is not None
        logger.info(
            "Discord connector ready as %s (id=%s)",
            self._client.user,
            self._client.user.id,
        )

    async def on_message(self, message: discord.Message) -> None:
        """Handle every incoming message from the gateway."""
        # Never process our own messages.
        if message.author == self._client.user:
            return

        # Guild filter.
        if self._settings.guild_ids and message.guild is not None and message.guild.id not in self._settings.guild_ids:
            return

        # Channel filter.
        if self._settings.channel_ids and message.channel.id not in self._settings.channel_ids:
            return

        normalized = await self._normalize(message)
        if self._publish is not None:
            payload = normalized.model_dump_json().encode()
            await self._publish("ingress.discord.message", payload)
            logger.debug("Published ingress event for message %s", message.id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _normalize(self, message: discord.Message) -> NormalizedMessage:
        """Convert a :class:`discord.Message` to a :class:`NormalizedMessage`."""
        # Determine thread_id: if the message is in a Thread use that id,
        # otherwise fall back to the channel id.
        thread_id = str(message.channel.id)

        attachments = await self._collect_attachments(message)

        # reply_to handling
        reply_to: str | None = None
        if message.reference and message.reference.message_id:
            reply_to = str(message.reference.message_id)

        # Extra metadata useful downstream.
        extra: dict[str, Any] = {}
        if message.guild is not None:
            extra["guild_id"] = str(message.guild.id)
            extra["guild_name"] = message.guild.name
        extra["channel_name"] = getattr(message.channel, "name", None)

        return NormalizedMessage(
            message_id=str(message.id),
            connector_type=self.connector_type,
            connector_account_id=self.account_id,
            thread_id=thread_id,
            sender_id=str(message.author.id),
            sender_display_name=message.author.display_name,
            content=message.content,
            attachments=attachments,
            timestamp=message.created_at.astimezone(UTC),
            reply_to=reply_to,
            extra=extra,
        )

    async def _collect_attachments(self, message: discord.Message) -> list[AttachmentRef]:
        """Build :class:`AttachmentRef` entries for each Discord attachment.

        For now the ``payload_ref`` stores the Discord CDN URL directly.  A
        future iteration will stream the bytes into S3-compatible object
        storage and return an ``s3://`` URI instead.
        """
        refs: list[AttachmentRef] = []
        for att in message.attachments:
            refs.append(
                AttachmentRef(
                    filename=att.filename,
                    content_type=att.content_type or "application/octet-stream",
                    size_bytes=att.size,
                    payload_ref=att.url,
                )
            )
        return refs
