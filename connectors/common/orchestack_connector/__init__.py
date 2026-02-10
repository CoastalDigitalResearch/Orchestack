"""Orchestack Connector Framework - Common base for all connectors."""

from orchestack_connector.attachments import (
    AttachmentManager,
    AttachmentTooLargeError,
)
from orchestack_connector.base import ConnectorBase
from orchestack_connector.config import ConnectorSettings
from orchestack_connector.identity import IdentityMapper, IdentityMapping
from orchestack_connector.message import AttachmentRef, NormalizedMessage

__all__ = [
    "AttachmentManager",
    "AttachmentRef",
    "AttachmentTooLargeError",
    "ConnectorBase",
    "ConnectorSettings",
    "IdentityMapper",
    "IdentityMapping",
    "NormalizedMessage",
]
