import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  EnvelopeSchema,
  type Actor,
  type Envelope,
  createEnvelope,
} from "../src/envelope.js";
import { validateEnvelope } from "../src/validation.js";
import { generateIdempotencyKey } from "../src/idempotency.js";
import { newULID, isValidULID } from "../src/ulid.js";
import { newTraceParent, parseTraceParent } from "../src/trace.js";

const testActor: Actor = { type: "system", id: "test-service", name: "Test" };

describe("Envelope", () => {
  it("should create with auto-generated fields", () => {
    const env = createEnvelope("task.created", testActor, "tenant-1");
    assert.equal(env.version, "1.0");
    assert.equal(env.event_type, "task.created");
    assert.equal(env.tenant_id, "tenant-1");
    assert.ok(isValidULID(env.event_id));
    assert.ok(env.timestamp);
  });

  it("should round-trip through JSON", () => {
    const env = createEnvelope("ingress.message", testActor, "tenant-2", {
      correlation_id: "corr-123",
      priority: 5,
      payload: { text: "hello" },
    });

    const json = JSON.stringify(env);
    const parsed = EnvelopeSchema.parse(JSON.parse(json));

    assert.equal(parsed.event_id, env.event_id);
    assert.equal(parsed.event_type, env.event_type);
    assert.equal(parsed.tenant_id, env.tenant_id);
    assert.equal(parsed.correlation_id, env.correlation_id);
    assert.equal(parsed.priority, env.priority);
  });

  it("should validate a valid envelope", () => {
    const env = createEnvelope("task.created", testActor, "tenant-1");
    const errors = validateEnvelope(env);
    assert.equal(errors.length, 0);
  });

  it("should detect invalid actor type", () => {
    const env = createEnvelope("task.created", testActor, "tenant-1");
    // Force an invalid actor type for validation testing.
    const bad = { ...env, actor: { type: "invalid" as any, id: "x" } };
    const errors = validateEnvelope(bad);
    assert.ok(errors.some((e) => e.includes("Invalid actor type")));
  });

  it("should reject via Zod schema for bad input", () => {
    assert.throws(() => {
      EnvelopeSchema.parse({ event_type: "", actor: { type: "bad", id: "" }, tenant_id: "" });
    });
  });
});

describe("Idempotency", () => {
  it("should generate correct key format", () => {
    const key = generateIdempotencyKey("tenant-1", "task-abc", 2, "model_call", 3);
    assert.equal(key, "idem:tenant-1:task-abc:2:model_call:3");
  });
});

describe("ULID", () => {
  it("should generate valid 26-char ULIDs", () => {
    const id = newULID();
    assert.equal(id.length, 26);
    assert.ok(isValidULID(id));
  });

  it("should generate unique ULIDs", () => {
    const seen = new Set<string>();
    for (let i = 0; i < 1000; i++) {
      const id = newULID();
      assert.ok(!seen.has(id), `Duplicate ULID: ${id}`);
      seen.add(id);
    }
  });

  it("should be monotonically increasing", () => {
    let prev = "";
    for (let i = 0; i < 100; i++) {
      const id = newULID();
      assert.ok(id > prev, `ULID not monotonic: ${id} <= ${prev}`);
      prev = id;
    }
  });

  it("should reject invalid ULIDs", () => {
    assert.ok(!isValidULID("short"));
    assert.ok(!isValidULID("!!!!!!!!!!!!!!!!!!!!!!!!!!!"));
  });
});

describe("TraceParent", () => {
  it("should generate valid traceparent", () => {
    const tp = newTraceParent();
    const { traceId, parentId, flags } = parseTraceParent(tp);
    assert.equal(traceId.length, 32);
    assert.equal(parentId.length, 16);
    assert.equal(flags, "01");
  });

  it("should reject invalid traceparent", () => {
    assert.throws(() => parseTraceParent("invalid"));
    assert.throws(() => parseTraceParent("01-abc-def-00"));
  });
});
