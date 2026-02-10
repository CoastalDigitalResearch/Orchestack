"""Email connector implementation using aioimaplib and aiosmtplib."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import re
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any

import aioimaplib
import aiosmtplib

from orchestack_connector.base import ConnectorBase
from orchestack_connector.message import AttachmentRef, NormalizedMessage
from orchestack_connector_email.config import EmailSettings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\n{3,}")


def _strip_html_fallback(html: str) -> str:
    """Minimal HTML-to-plain-text conversion when *markdownify* is absent."""
    text = _HTML_TAG_RE.sub("", html)
    text = _WHITESPACE_RE.sub("\n\n", text)
    return text.strip()


def _html_to_markdown(html: str) -> str:
    """Convert HTML body to Markdown, falling back to regex strip."""
    try:
        import markdownify  # type: ignore[import-untyped]

        return markdownify.markdownify(html).strip()
    except ImportError:
        return _strip_html_fallback(html)


def _extract_thread_root(message_id: str | None, in_reply_to: str | None, references: str | None) -> str:
    """Determine the thread root Message-ID.

    Uses the first entry in the ``References`` header when available,
    otherwise falls back to ``In-Reply-To``, and finally the message's own
    ``Message-ID``.
    """
    if references:
        # References is a space-separated list of Message-IDs.
        parts = references.strip().split()
        if parts:
            return parts[0]
    if in_reply_to:
        return in_reply_to.strip().split()[0]
    return message_id or ""


def _parse_email_message(raw_bytes: bytes) -> EmailMessage:
    """Parse raw bytes into a stdlib ``EmailMessage``."""
    from email import message_from_bytes

    return message_from_bytes(raw_bytes, policy=policy.default)  # type: ignore[return-value]


def _extract_body(msg: EmailMessage) -> str:
    """Extract the best text body from a parsed email."""
    # Prefer plain text
    plain_part = msg.get_body(preferencelist=("plain",))
    if plain_part is not None:
        content = plain_part.get_content()
        if isinstance(content, str):
            return content.strip()

    # Fall back to HTML -> Markdown
    html_part = msg.get_body(preferencelist=("html",))
    if html_part is not None:
        content = html_part.get_content()
        if isinstance(content, str):
            return _html_to_markdown(content)

    return ""


def _extract_attachments(msg: EmailMessage) -> list[AttachmentRef]:
    """Walk MIME parts and collect attachment references."""
    attachments: list[AttachmentRef] = []
    for part in msg.iter_attachments():
        filename = part.get_filename() or "unnamed"
        content_type = part.get_content_type()
        payload = part.get_content()
        if isinstance(payload, str):
            size_bytes = len(payload.encode())
        elif isinstance(payload, bytes):
            size_bytes = len(payload)
        else:
            size_bytes = 0

        # Build a deterministic ref key from message-id + filename.
        ref_hash = hashlib.sha256(f"{msg['Message-ID']}:{filename}".encode()).hexdigest()[:16]
        payload_ref = f"email://{ref_hash}/{filename}"

        attachments.append(
            AttachmentRef(
                filename=filename,
                content_type=content_type,
                size_bytes=size_bytes,
                payload_ref=payload_ref,
            )
        )
    return attachments


def _sender_display_name(msg: EmailMessage) -> str:
    """Extract a human-readable sender display name."""
    raw_from = msg["From"] or ""
    display, addr = parseaddr(str(raw_from))
    return display or addr


def _sender_id(msg: EmailMessage) -> str:
    """Extract the raw email address of the sender."""
    raw_from = msg["From"] or ""
    _, addr = parseaddr(str(raw_from))
    return addr


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class EmailConnector(ConnectorBase):
    """IMAP/SMTP connector for Orchestack."""

    def __init__(self, settings: EmailSettings) -> None:
        super().__init__(connector_type="email", account_id=settings.imap_user)
        self.settings = settings
        self._imap: aioimaplib.IMAP4_SSL | aioimaplib.IMAP4 | None = None
        self._poll_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # ConnectorBase interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish the IMAP connection and authenticate."""
        self._imap = await self._create_imap_client()
        await self._imap.wait_hello_from_server()
        await self._imap.login(self.settings.imap_user, self.settings.imap_password)
        logger.info(
            "IMAP connected to %s:%s as %s",
            self.settings.imap_host,
            self.settings.imap_port,
            self.settings.imap_user,
        )

    async def listen(self) -> None:
        """Start the IMAP polling loop as a background task.

        The polling loop runs until ``stop()`` is called.  It is safe
        to ``await`` this method -- it returns immediately after scheduling
        the background task.
        """
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def send(self, channel: str, message: str, **kwargs: Any) -> None:
        """Send an email via SMTP.

        Parameters
        ----------
        channel:
            Recipient email address.
        message:
            Markdown body text.
        **kwargs:
            Optional keys:
            - ``subject``  : email subject line (str)
            - ``in_reply_to`` : Message-ID being replied to (str)
            - ``references``  : space-separated list of Message-IDs (str)
            - ``attachments`` : list of dicts with ``filename``, ``content_type``, ``data`` (bytes)
        """
        subject: str = kwargs.get("subject", "")
        in_reply_to: str | None = kwargs.get("in_reply_to")
        references: str | None = kwargs.get("references")
        attachment_list: list[dict[str, Any]] = kwargs.get("attachments", [])

        email_msg = self._build_outgoing_message(
            to_address=channel,
            subject=subject,
            body_markdown=message,
            in_reply_to=in_reply_to,
            references=references,
            attachments=attachment_list,
        )

        await self._send_smtp(email_msg)
        logger.info("Email sent to %s subject=%r", channel, subject)

    async def map_identity(self, sender_id: str) -> dict[str, Any]:
        """Map an email address to an Orchestack identity stub."""
        return {
            "connector_type": "email",
            "platform_id": sender_id,
        }

    async def stop(self) -> None:
        """Gracefully shut down the IMAP connection and polling task."""
        await super().stop()
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
        if self._imap is not None:
            try:
                await self._imap.logout()
            except Exception:
                logger.debug("IMAP logout error (ignored during shutdown)", exc_info=True)
            self._imap = None

    # ------------------------------------------------------------------
    # IMAP polling
    # ------------------------------------------------------------------

    async def _create_imap_client(self) -> aioimaplib.IMAP4_SSL | aioimaplib.IMAP4:
        """Create the appropriate IMAP client based on TLS setting."""
        if self.settings.use_tls:
            return aioimaplib.IMAP4_SSL(
                host=self.settings.imap_host,
                port=self.settings.imap_port,
            )
        return aioimaplib.IMAP4(
            host=self.settings.imap_host,
            port=self.settings.imap_port,
        )

    async def _poll_loop(self) -> None:
        """Periodically poll for UNSEEN messages."""
        assert self._imap is not None
        while self._running:
            try:
                messages = await self._fetch_unseen()
                for normalized in messages:
                    await self._on_message(normalized)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error during IMAP poll cycle")
            await asyncio.sleep(self.settings.poll_interval_s)

    async def _fetch_unseen(self) -> list[NormalizedMessage]:
        """Fetch all UNSEEN messages from the configured mailbox."""
        assert self._imap is not None
        results: list[NormalizedMessage] = []

        await self._imap.select(self.settings.mailbox)

        status, data = await self._imap.search("UNSEEN")
        if status != "OK":
            logger.warning("IMAP SEARCH UNSEEN returned status=%s", status)
            return results

        # data is a list; the first element contains the space-separated UIDs.
        uid_line = data[0] if data else ""
        if isinstance(uid_line, bytes):
            uid_line = uid_line.decode()
        uids = uid_line.strip().split()
        if not uids or uids == [""]:
            return results

        for uid in uids:
            try:
                normalized = await self._fetch_one(uid)
                if normalized is not None:
                    results.append(normalized)
            except Exception:
                logger.exception("Failed to fetch/parse UID %s", uid)

        return results

    async def _fetch_one(self, uid: str) -> NormalizedMessage | None:
        """Fetch a single message by UID and convert to NormalizedMessage."""
        assert self._imap is not None
        status, data = await self._imap.fetch(uid, "(RFC822)")
        if status != "OK":
            logger.warning("IMAP FETCH %s returned status=%s", uid, status)
            return None

        # aioimaplib returns data as a list; find the bytes payload.
        raw_bytes: bytes | None = None
        for item in data:
            if isinstance(item, bytes):
                raw_bytes = item
                break
            if isinstance(item, tuple):
                for part in item:
                    if isinstance(part, bytes):
                        raw_bytes = part
                        break
                if raw_bytes is not None:
                    break

        if raw_bytes is None:
            logger.warning("No RFC822 bytes found for UID %s", uid)
            return None

        msg = _parse_email_message(raw_bytes)

        message_id = str(msg["Message-ID"] or f"<uid-{uid}@local>")
        in_reply_to = str(msg["In-Reply-To"] or "") or None
        references = str(msg["References"] or "") or None
        subject = str(msg["Subject"] or "")
        date_str = msg["Date"]
        try:
            from email.utils import parsedate_to_datetime

            timestamp = parsedate_to_datetime(str(date_str))
        except Exception:
            timestamp = datetime.now(UTC)

        thread_id = _extract_thread_root(message_id, in_reply_to, references)
        body = _extract_body(msg)
        attachments = _extract_attachments(msg)
        content = f"Subject: {subject}\n\n{body}" if subject else body

        return NormalizedMessage(
            message_id=message_id,
            connector_type="email",
            connector_account_id=self.account_id,
            thread_id=thread_id,
            sender_id=_sender_id(msg),
            sender_display_name=_sender_display_name(msg),
            content=content,
            attachments=attachments,
            timestamp=timestamp,
            reply_to=in_reply_to,
            extra={
                "subject": subject,
                "references": references,
                "in_reply_to": in_reply_to,
            },
        )

    async def _on_message(self, normalized: NormalizedMessage) -> None:
        """Callback invoked for each new inbound message.

        In production this publishes to NATS.  The actual publishing is
        wired up in ``main.py``; this method is overridden at runtime.
        """
        logger.info(
            "Received email message_id=%s from=%s",
            normalized.message_id,
            normalized.sender_id,
        )

    # ------------------------------------------------------------------
    # SMTP sending
    # ------------------------------------------------------------------

    def _build_outgoing_message(
        self,
        to_address: str,
        subject: str,
        body_markdown: str,
        in_reply_to: str | None = None,
        references: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> EmailMessage:
        """Construct a MIME ``EmailMessage`` ready for SMTP submission."""
        msg = EmailMessage()
        msg["From"] = self.settings.from_address
        msg["To"] = to_address

        # Subject with Re: prefix for replies
        if in_reply_to and not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        msg["Subject"] = subject

        # Threading headers
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references
        elif in_reply_to:
            msg["References"] = in_reply_to

        # Plain text body
        msg.set_content(body_markdown)

        # HTML alternative via simple Markdown -> HTML
        html_body = self._markdown_to_html(body_markdown)
        msg.add_alternative(html_body, subtype="html")

        # Attachments
        for att in attachments or []:
            filename = att.get("filename", "attachment")
            content_type = att.get("content_type", "application/octet-stream")
            data: bytes = att.get("data", b"")
            maintype, _, subtype = content_type.partition("/")
            msg.add_attachment(
                data,
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=filename,
            )

        return msg

    @staticmethod
    def _markdown_to_html(md_text: str) -> str:
        """Best-effort Markdown to HTML conversion."""
        try:
            import markdown  # type: ignore[import-untyped]

            return markdown.markdown(md_text)
        except ImportError:
            # Minimal fallback: wrap paragraphs in <p> tags.
            paragraphs = md_text.split("\n\n")
            html_parts = [f"<p>{p.strip()}</p>" for p in paragraphs if p.strip()]
            return "\n".join(html_parts)

    async def _send_smtp(self, msg: EmailMessage) -> None:
        """Send an ``EmailMessage`` via SMTP."""
        smtp_kwargs: dict[str, Any] = {
            "hostname": self.settings.smtp_host,
            "port": self.settings.smtp_port,
            "username": self.settings.smtp_user,
            "password": self.settings.smtp_password,
        }
        if self.settings.use_tls:
            smtp_kwargs["start_tls"] = True

        await aiosmtplib.send(msg, **smtp_kwargs)
