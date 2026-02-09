"""Idempotency key generation per RFC-001."""


def generate_idempotency_key(
    tenant_id: str,
    task_id: str,
    run_attempt: int,
    step_type: str,
    step_seq: int,
) -> str:
    """Generate idempotency key: idem:{tenant}:{task_id}:{run_attempt}:{step_type}:{step_seq}."""
    return f"idem:{tenant_id}:{task_id}:{run_attempt}:{step_type}:{step_seq}"
