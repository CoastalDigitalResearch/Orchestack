"""Orchestack Slack Connector — bridges Slack workspaces to the Orchestack bus."""

from orchestack_connector_slack.config import SlackConnectorSettings
from orchestack_connector_slack.connector import SlackConnector

__all__ = ["SlackConnector", "SlackConnectorSettings"]
