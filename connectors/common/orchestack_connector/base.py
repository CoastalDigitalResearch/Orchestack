"""Base class for all connectors."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from orchestack_connector.message import NormalizedMessage

logger = logging.getLogger(__name__)


class ConnectorBase(ABC):
    """Abstract base class for Orchestack connectors."""

    def __init__(self, connector_type: str, account_id: str):
        self.connector_type = connector_type
        self.account_id = account_id
        self._running = False

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

    async def start(self) -> None:
        """Start the connector."""
        self._running = True
        logger.info("Starting connector: %s/%s", self.connector_type, self.account_id)
        await self.connect()
        await self.listen()

    async def stop(self) -> None:
        """Stop the connector gracefully."""
        self._running = False
        logger.info("Stopping connector: %s/%s", self.connector_type, self.account_id)
