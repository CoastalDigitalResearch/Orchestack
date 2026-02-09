"""Envelope validation rules."""

from __future__ import annotations

from orchestack_envelope.envelope import Envelope

VALID_ACTOR_TYPES = {"user", "agent", "system", "connector"}
VALID_VERSIONS = {"1.0"}


def validate_envelope(envelope: Envelope) -> list[str]:
    """Validate an envelope, returning a list of errors (empty if valid)."""
    errors: list[str] = []

    if envelope.version not in VALID_VERSIONS:
        errors.append(f"Invalid version: {envelope.version}")

    if not envelope.event_id:
        errors.append("event_id is required")

    if not envelope.event_type:
        errors.append("event_type is required")

    if not envelope.tenant_id:
        errors.append("tenant_id is required")

    if envelope.actor.type not in VALID_ACTOR_TYPES:
        errors.append(f"Invalid actor type: {envelope.actor.type}")

    if not envelope.actor.id:
        errors.append("actor.id is required")

    if envelope.priority < 0 or envelope.priority > 10:
        errors.append(f"Priority must be 0-10, got {envelope.priority}")

    return errors
