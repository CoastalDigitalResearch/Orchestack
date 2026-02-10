"""Orchestack Email Connector - bridges IMAP/SMTP email to the Orchestack mesh."""

from orchestack_connector_email.config import EmailSettings
from orchestack_connector_email.connector import EmailConnector

__all__ = ["EmailConnector", "EmailSettings"]
