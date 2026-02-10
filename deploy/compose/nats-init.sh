#!/bin/sh
set -e

# ---------------------------------------------------------------------------
# nats-init.sh  --  Idempotent JetStream stream & consumer bootstrap
# Per RFC-001 section 8 (Message Bus Topology)
# ---------------------------------------------------------------------------

NATS_URL="${NATS_URL:-nats://nats:4222}"
export NATS_URL

# ---------------------------------------------------------------------------
# Wait for NATS to be reachable
# ---------------------------------------------------------------------------
echo "Waiting for NATS at ${NATS_URL} ..."
until nats server check connection --server="${NATS_URL}" >/dev/null 2>&1; do
  echo "  NATS not ready yet -- retrying in 2s"
  sleep 2
done
echo "NATS is available."

# Verify JetStream is enabled
until nats server check jetstream --server="${NATS_URL}" >/dev/null 2>&1; do
  echo "  JetStream not ready yet -- retrying in 2s"
  sleep 2
done
echo "JetStream is enabled."

# ---------------------------------------------------------------------------
# Helper: create or update a stream (idempotent)
# ---------------------------------------------------------------------------
create_stream() {
  name="$1"; shift
  echo "--- Stream: ${name}"
  if nats stream info "${name}" >/dev/null 2>&1; then
    echo "  Updating existing stream ${name}"
    nats stream update "${name}" "$@" --force
  else
    echo "  Creating stream ${name}"
    nats stream add "${name}" "$@"
  fi
}

# ---------------------------------------------------------------------------
# Helper: create or update a durable pull consumer (idempotent)
# ---------------------------------------------------------------------------
create_consumer() {
  stream="$1"; shift
  name="$1"; shift
  echo "--- Consumer: ${name} on ${stream}"
  if nats consumer info "${stream}" "${name}" >/dev/null 2>&1; then
    echo "  Consumer ${name} already exists on ${stream} -- skipping"
  else
    echo "  Creating consumer ${name} on ${stream}"
    nats consumer add "${stream}" "${name}" "$@"
  fi
}

# ===========================================================================
# STREAMS
# ===========================================================================

# STREAM_TASKS -- work-queue for dispatched task items
# Retention: work-queue (messages removed once ack'd)
# Max age: 7 days  |  Max bytes: 1 GB
create_stream STREAM_TASKS \
  --subjects "tasks.>" \
  --retention work \
  --max-age "7d" \
  --max-bytes 1073741824 \
  --storage file \
  --replicas 1 \
  --discard old \
  --dupe-window "2m" \
  --defaults

# STREAM_EVENTS -- fan-out event bus
# Subjects: ingress, memory, router, heartbeat
# Retention: limits  |  Max age: 24h  |  Max bytes: 5 GB
create_stream STREAM_EVENTS \
  --subjects "ingress.>,memory.>,router.>,heartbeat.>" \
  --retention limits \
  --max-age "24h" \
  --max-bytes 5368709120 \
  --storage file \
  --replicas 1 \
  --discard old \
  --dupe-window "2m" \
  --defaults

# STREAM_AUDIT -- long-lived audit trail
# Retention: limits  |  Max age: 90 days  |  Max bytes: 10 GB
create_stream STREAM_AUDIT \
  --subjects "audit.>" \
  --retention limits \
  --max-age "90d" \
  --max-bytes 10737418240 \
  --storage file \
  --replicas 1 \
  --discard old \
  --dupe-window "2m" \
  --defaults

# ===========================================================================
# CONSUMERS  (pull-based, explicit ack, exponential backoff)
# ===========================================================================

# Exponential backoff schedule shared by all consumers:
#   1s -> 5s -> 30s -> 60s -> 300s
BACKOFF="1s,5s,30s,60s,300s"

# Session-scheduler listens for new ingress messages
create_consumer STREAM_EVENTS CONSUMER_SESSION_SCHEDULER \
  --pull \
  --deliver all \
  --ack explicit \
  --max-deliver 10 \
  --backoff-mode linear \
  --backoff "${BACKOFF}" \
  --filter "ingress.>" \
  --defaults

# Task-dispatcher consumes the full tasks stream
create_consumer STREAM_TASKS CONSUMER_TASK_DISPATCHER \
  --pull \
  --deliver all \
  --ack explicit \
  --max-deliver 10 \
  --backoff-mode linear \
  --backoff "${BACKOFF}" \
  --filter "tasks.>" \
  --defaults

# Loop-runner only picks up dispatched tasks
create_consumer STREAM_TASKS CONSUMER_LOOP_RUNNER \
  --pull \
  --deliver all \
  --ack explicit \
  --max-deliver 10 \
  --backoff-mode linear \
  --backoff "${BACKOFF}" \
  --filter "tasks.dispatch" \
  --defaults

# Budget-accounting tracks router metrics
create_consumer STREAM_EVENTS CONSUMER_BUDGET_ACCOUNTING \
  --pull \
  --deliver all \
  --ack explicit \
  --max-deliver 10 \
  --backoff-mode linear \
  --backoff "${BACKOFF}" \
  --filter "router.metrics" \
  --defaults

# Memory-plane receives memory-related events
create_consumer STREAM_EVENTS CONSUMER_MEMORY_PLANE \
  --pull \
  --deliver all \
  --ack explicit \
  --max-deliver 10 \
  --backoff-mode linear \
  --backoff "${BACKOFF}" \
  --filter "memory.>" \
  --defaults

# Audit-writer persists all audit events
create_consumer STREAM_AUDIT CONSUMER_AUDIT_WRITER \
  --pull \
  --deliver all \
  --ack explicit \
  --max-deliver 10 \
  --backoff-mode linear \
  --backoff "${BACKOFF}" \
  --filter "audit.>" \
  --defaults

# ===========================================================================
echo ""
echo "=== NATS JetStream initialization complete ==="
echo ""
echo "Streams:"
nats stream list
echo ""
echo "Consumers on STREAM_TASKS:"
nats consumer list STREAM_TASKS
echo ""
echo "Consumers on STREAM_EVENTS:"
nats consumer list STREAM_EVENTS
echo ""
echo "Consumers on STREAM_AUDIT:"
nats consumer list STREAM_AUDIT
