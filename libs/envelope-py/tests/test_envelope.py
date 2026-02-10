"""Tests for the envelope library."""

from orchestack_envelope import Actor, Envelope, generate_idempotency_key, validate_envelope


class TestEnvelope:
    def test_create_envelope(self):
        env = Envelope(
            event_type="ingress.discord.message",
            actor=Actor(type="connector", id="discord-001"),
            tenant_id="tenant-default",
        )
        assert env.version == "1.0"
        assert env.event_id  # auto-generated ULID
        assert env.event_type == "ingress.discord.message"
        assert env.tenant_id == "tenant-default"

    def test_json_roundtrip(self):
        env = Envelope(
            event_type="tasks.create",
            actor=Actor(type="system", id="session-scheduler"),
            tenant_id="tenant-default",
            payload={"task_id": "task-001"},
        )
        json_str = env.to_json()
        restored = Envelope.from_json(json_str)
        assert restored.event_type == env.event_type
        assert restored.payload == env.payload

    def test_validation_valid(self):
        env = Envelope(
            event_type="tasks.create",
            actor=Actor(type="system", id="scheduler"),
            tenant_id="tenant-default",
        )
        errors = validate_envelope(env)
        assert errors == []

    def test_validation_invalid_actor(self):
        env = Envelope(
            event_type="test",
            actor=Actor(type="invalid", id="x"),
            tenant_id="t",
        )
        errors = validate_envelope(env)
        assert any("Invalid actor type" in e for e in errors)

    def test_idempotency_key(self):
        key = generate_idempotency_key("tenant-1", "task-001", 1, "model_call", 3)
        assert key == "idem:tenant-1:task-001:1:model_call:3"
