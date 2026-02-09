"""Orchestack Connector Framework - Common base for all connectors."""

from orchestack_connector.base import ConnectorBase
from orchestack_connector.message import AttachmentRef, NormalizedMessage

__all__ = ["ConnectorBase", "NormalizedMessage", "AttachmentRef"]
