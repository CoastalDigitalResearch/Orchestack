#!/bin/sh
# NATS JetStream stream initialization
# Creates the three core streams defined in RFC-001 §8

set -e

NATS_URL="${NATS_URL:-nats://nats:4222}"

echo "Waiting for NATS to be ready..."
until nats server check connection --server="$NATS_URL" 2>/dev/null; do
    sleep 1
done
echo "NATS is ready."

# STREAM_TASKS - Work-queue retention for task processing
nats stream add STREAM_TASKS \
    --server="$NATS_URL" \
    --subjects="tasks.>" \
    --retention=work \
    --max-age=7d \
    --storage=file \
    --replicas=1 \
    --discard=old \
    --max-msgs=-1 \
    --max-bytes=-1 \
    --max-msg-size=-1 \
    --dupe-window=2m \
    --no-allow-rollup \
    --deny-delete \
    --deny-purge \
    2>/dev/null || echo "STREAM_TASKS already exists"

# STREAM_EVENTS - Limits retention for general events
nats stream add STREAM_EVENTS \
    --server="$NATS_URL" \
    --subjects="ingress.>,memory.>,router.>,heartbeat.>,egress.>,payments.>,trust.>,ext.>" \
    --retention=limits \
    --max-age=24h \
    --storage=file \
    --replicas=1 \
    --discard=old \
    --max-msgs=-1 \
    --max-bytes=-1 \
    --max-msg-size=-1 \
    --dupe-window=2m \
    2>/dev/null || echo "STREAM_EVENTS already exists"

# STREAM_AUDIT - Long retention for audit trail
nats stream add STREAM_AUDIT \
    --server="$NATS_URL" \
    --subjects="audit.>" \
    --retention=limits \
    --max-age=90d \
    --storage=file \
    --replicas=1 \
    --discard=old \
    --max-msgs=-1 \
    --max-bytes=-1 \
    --max-msg-size=-1 \
    --dupe-window=2m \
    --deny-delete \
    --deny-purge \
    2>/dev/null || echo "STREAM_AUDIT already exists"

echo "All streams configured successfully."
echo "Streams:"
nats stream ls --server="$NATS_URL"
