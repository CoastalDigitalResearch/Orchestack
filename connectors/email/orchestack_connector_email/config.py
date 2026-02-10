"""Configuration for the Orchestack Email connector."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class EmailSettings(BaseSettings):
    """Email connector settings loaded from environment variables.

    All variables are prefixed with ``ORCHESTACK_EMAIL_``.  For example
    the IMAP host is read from ``ORCHESTACK_EMAIL_IMAP_HOST``.
    """

    model_config = {"env_prefix": "ORCHESTACK_EMAIL_"}

    # --- IMAP (inbound) ---
    imap_host: str = Field(
        ...,
        description="IMAP server hostname (required).",
    )
    imap_port: int = Field(
        default=993,
        description="IMAP server port.",
    )
    imap_user: str = Field(
        ...,
        description="IMAP login username (required).",
    )
    imap_password: str = Field(
        ...,
        description="IMAP login password (required).",
    )

    # --- SMTP (outbound) ---
    smtp_host: str = Field(
        ...,
        description="SMTP server hostname (required).",
    )
    smtp_port: int = Field(
        default=587,
        description="SMTP server port.",
    )
    smtp_user: str = Field(
        ...,
        description="SMTP login username (required).",
    )
    smtp_password: str = Field(
        ...,
        description="SMTP login password (required).",
    )

    # --- TLS ---
    use_tls: bool = Field(
        default=True,
        description="Enable TLS for both IMAP and SMTP connections.",
    )

    # --- Polling ---
    poll_interval_s: int = Field(
        default=30,
        description="Seconds between IMAP UNSEEN mail checks.",
    )

    # --- NATS ---
    nats_url: str = Field(
        default="nats://localhost:4222",
        description="NATS server URL.",
    )

    # --- Mailbox ---
    mailbox: str = Field(
        default="INBOX",
        description="IMAP mailbox (folder) to monitor.",
    )

    # --- From address ---
    from_address: str = Field(
        ...,
        description="Email address the bot sends from (required).",
    )
