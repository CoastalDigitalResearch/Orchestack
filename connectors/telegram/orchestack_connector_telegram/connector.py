"""Telegram connector implementation using python-telegram-bot v21+ async API."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from telegram import Bot, InlineKeyboardMarkup, Message, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

from orchestack_connector.base import ConnectorBase
from orchestack_connector.message import AttachmentRef, NormalizedMessage
from orchestack_connector_telegram.config import TelegramSettings

logger = logging.getLogger(__name__)

# Maximum attachment size we will download inline (10 MiB).
_MAX_INLINE_ATTACHMENT_BYTES = 10 * 1024 * 1024


class TelegramConnector(ConnectorBase):
    """Orchestack connector for Telegram using python-telegram-bot v21+.

    Parameters
    ----------
    settings:
        Validated :class:`TelegramSettings` instance.
    publish_callback:
        Async callable that receives ``(subject: str, data: bytes)`` and
        publishes the payload to NATS.  Injected by the entrypoint so the
        connector itself stays transport-agnostic.
    """

    def __init__(
        self,
        settings: TelegramSettings,
        publish_callback: Any | None = None,
    ) -> None:
        super().__init__(connector_type="telegram", account_id="default")
        self._settings = settings
        self._publish = publish_callback
        self._application: Application | None = None  # type: ignore[type-arg]
        self._polling_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # ConnectorBase interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Build the python-telegram-bot Application and initialize it."""
        logger.info("Building Telegram application...")
        self._application = Application.builder().token(self._settings.bot_token).build()

        # Register the message handler for all text messages, photos,
        # documents, and other content types.
        handler = MessageHandler(
            filters.ALL & ~filters.COMMAND & ~filters.UpdateType.EDITED_MESSAGE,
            self._handle_message,
        )
        self._application.add_handler(handler)

        # Initialize the application (sets up the bot, updater, etc.)
        await self._application.initialize()
        logger.info("Telegram application initialized.")

    async def listen(self) -> None:
        """Start receiving updates via long polling or webhook.

        The polling/webhook loop runs in the background so this method
        returns immediately.
        """
        assert self._application is not None

        if self._settings.use_polling:
            logger.info("Starting Telegram long polling...")
            # Start the updater for polling
            await self._application.start()
            await self._application.updater.start_polling(  # type: ignore[union-attr]
                drop_pending_updates=True,
            )
        else:
            webhook_url = self._settings.webhook_url
            if not webhook_url:
                raise ValueError("webhook_url must be set when use_polling is False")
            logger.info(
                "Starting Telegram webhook on port %d -> %s",
                self._settings.webhook_port,
                webhook_url,
            )
            await self._application.start()
            await self._application.updater.start_webhook(  # type: ignore[union-attr]
                listen="0.0.0.0",
                port=self._settings.webhook_port,
                url_path="/telegram/webhook",
                webhook_url=f"{webhook_url}/telegram/webhook",
                drop_pending_updates=True,
            )

    async def send(self, channel: str, message: str, **kwargs: Any) -> None:
        """Send a message to a Telegram chat.

        Parameters
        ----------
        channel:
            The Telegram chat ID (as a string) to send the message to.
        message:
            The text content to send.  Parsed as MarkdownV2 by default.
        **kwargs:
            Optional extra arguments:

            - ``parse_mode``: Override parse mode (default ``MarkdownV2``).
            - ``reply_markup``: An :class:`InlineKeyboardMarkup` dict or
              object for inline keyboards (approval workflows, etc.).
            - ``reply_to_message_id``: Integer message ID to reply to.
            - ``file_bytes``: Raw ``bytes`` of a file to attach.
            - ``file_name``: Filename for the attachment (default
              ``"attachment"``).
            - ``content_type``: MIME type hint for file dispatch.
            - ``message_thread_id``: Topic thread ID for supergroups with
              topics enabled.
        """
        assert self._application is not None
        bot: Bot = self._application.bot

        chat_id = int(channel)
        parse_mode = kwargs.get("parse_mode", ParseMode.MARKDOWN_V2)
        reply_to_message_id: int | None = kwargs.get("reply_to_message_id")
        message_thread_id: int | None = kwargs.get("message_thread_id")

        # Build reply_markup from dict if provided.
        reply_markup = kwargs.get("reply_markup")
        if isinstance(reply_markup, dict):
            reply_markup = InlineKeyboardMarkup.de_json(reply_markup, bot)

        # File attachment handling.
        file_bytes: bytes | None = kwargs.get("file_bytes")
        if file_bytes is not None:
            file_name: str = kwargs.get("file_name", "attachment")
            content_type: str = kwargs.get("content_type", "application/octet-stream")
            try:
                if content_type.startswith("image/"):
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=file_bytes,
                        caption=message or None,
                        parse_mode=parse_mode if message else None,
                        reply_to_message_id=reply_to_message_id,
                        message_thread_id=message_thread_id,
                    )
                else:
                    await bot.send_document(
                        chat_id=chat_id,
                        document=file_bytes,
                        filename=file_name,
                        caption=message or None,
                        parse_mode=parse_mode if message else None,
                        reply_to_message_id=reply_to_message_id,
                        message_thread_id=message_thread_id,
                    )
                logger.info("Sent file to chat %s.", channel)
            except Exception:
                logger.exception("Failed to send file to chat %s.", channel)
            return

        # Text message.
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                reply_to_message_id=reply_to_message_id,
                message_thread_id=message_thread_id,
            )
            logger.info("Sent message to chat %s.", channel)
        except Exception:
            logger.exception("Failed to send message to chat %s.", channel)

    async def map_identity(self, sender_id: str) -> dict[str, Any]:
        """Return a minimal identity mapping for *sender_id*."""
        return {
            "connector_type": self.connector_type,
            "platform_id": sender_id,
        }

    async def stop(self) -> None:
        """Gracefully shut down the Telegram bot."""
        logger.info("Shutting down Telegram connector...")
        if self._application is not None:
            if self._application.updater is not None:
                await self._application.updater.stop()
            await self._application.stop()
            await self._application.shutdown()
            self._application = None
        await super().stop()

    # ------------------------------------------------------------------
    # Telegram message handler
    # ------------------------------------------------------------------

    async def _handle_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle every incoming Telegram message update."""
        if update.message is None:
            return

        message = update.message

        # Filter by allowed chat IDs if configured.
        if self._settings.allowed_chat_ids and message.chat_id not in self._settings.allowed_chat_ids:
            return

        # Ignore messages from bots (including ourselves).
        if message.from_user is None or message.from_user.is_bot:
            return

        normalized = await self._normalize(message)

        if self._publish is not None:
            payload = normalized.model_dump_json().encode()
            await self._publish("ingress.telegram.message", payload)
            logger.debug(
                "Published ingress event for message %s in chat %s",
                message.message_id,
                message.chat_id,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _normalize(self, message: Message) -> NormalizedMessage:
        """Convert a Telegram :class:`Message` to a :class:`NormalizedMessage`."""
        # Thread ID: use chat_id, or chat_id:message_thread_id for topics.
        thread_id = str(message.chat_id)
        if message.message_thread_id is not None:
            thread_id = f"{message.chat_id}:{message.message_thread_id}"

        # Sender info.
        sender = message.from_user
        sender_id = str(sender.id) if sender else "unknown"
        display_name = sender.full_name or sender.username or sender_id if sender else "Unknown"

        # Content: prefer text, fall back to caption for media messages.
        content = message.text or message.caption or ""

        # Attachments.
        attachments = await self._collect_attachments(message)

        # Reply-to handling.
        reply_to: str | None = None
        if message.reply_to_message is not None:
            reply_to = str(message.reply_to_message.message_id)

        # Extra metadata.
        extra: dict[str, Any] = {
            "chat_type": message.chat.type,
        }
        if message.chat.title:
            extra["chat_title"] = message.chat.title
        if sender and sender.username:
            extra["sender_username"] = sender.username
        if message.message_thread_id is not None:
            extra["message_thread_id"] = message.message_thread_id

        return NormalizedMessage(
            message_id=str(message.message_id),
            connector_type=self.connector_type,
            connector_account_id=self.account_id,
            thread_id=thread_id,
            sender_id=sender_id,
            sender_display_name=display_name,
            content=content,
            attachments=attachments,
            timestamp=(message.date.astimezone(UTC) if message.date else datetime.now(UTC)),
            reply_to=reply_to,
            extra=extra,
        )

    async def _collect_attachments(self, message: Message) -> list[AttachmentRef]:
        """Build :class:`AttachmentRef` entries for Telegram attachments.

        Downloads file metadata from the Telegram API.  The ``payload_ref``
        stores the Telegram file_id for now; a future iteration will stream
        bytes into S3-compatible object storage and return an ``s3://`` URI.
        """
        refs: list[AttachmentRef] = []

        # Photo: pick the largest resolution.
        if message.photo:
            largest = message.photo[-1]
            file = await largest.get_file()
            refs.append(
                AttachmentRef(
                    filename=f"photo_{largest.file_unique_id}.jpg",
                    content_type="image/jpeg",
                    size_bytes=largest.file_size or 0,
                    payload_ref=f"telegram://{file.file_id}",
                )
            )

        # Document.
        if message.document:
            doc = message.document
            file = await doc.get_file()
            refs.append(
                AttachmentRef(
                    filename=doc.file_name or f"document_{doc.file_unique_id}",
                    content_type=doc.mime_type or "application/octet-stream",
                    size_bytes=doc.file_size or 0,
                    payload_ref=f"telegram://{file.file_id}",
                )
            )

        # Audio.
        if message.audio:
            audio = message.audio
            file = await audio.get_file()
            refs.append(
                AttachmentRef(
                    filename=(audio.file_name or f"audio_{audio.file_unique_id}.mp3"),
                    content_type=audio.mime_type or "audio/mpeg",
                    size_bytes=audio.file_size or 0,
                    payload_ref=f"telegram://{file.file_id}",
                )
            )

        # Video.
        if message.video:
            video = message.video
            file = await video.get_file()
            refs.append(
                AttachmentRef(
                    filename=(video.file_name or f"video_{video.file_unique_id}.mp4"),
                    content_type=video.mime_type or "video/mp4",
                    size_bytes=video.file_size or 0,
                    payload_ref=f"telegram://{file.file_id}",
                )
            )

        # Voice note.
        if message.voice:
            voice = message.voice
            file = await voice.get_file()
            refs.append(
                AttachmentRef(
                    filename=f"voice_{voice.file_unique_id}.ogg",
                    content_type=voice.mime_type or "audio/ogg",
                    size_bytes=voice.file_size or 0,
                    payload_ref=f"telegram://{file.file_id}",
                )
            )

        # Sticker.
        if message.sticker:
            sticker = message.sticker
            file = await sticker.get_file()
            refs.append(
                AttachmentRef(
                    filename=f"sticker_{sticker.file_unique_id}.webp",
                    content_type="image/webp",
                    size_bytes=sticker.file_size or 0,
                    payload_ref=f"telegram://{file.file_id}",
                )
            )

        return refs
