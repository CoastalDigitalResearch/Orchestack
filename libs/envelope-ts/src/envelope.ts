/**
 * RFC-001 §5.1 Event Envelope types and Zod schemas.
 */
import { z } from "zod";
import { newULID } from "./ulid.js";

export const ActorSchema = z.object({
  type: z.enum(["user", "agent", "system", "connector"]),
  id: z.string().min(1),
  name: z.string().optional(),
});

export type Actor = z.infer<typeof ActorSchema>;

export const TraceContextSchema = z.object({
  traceparent: z.string().optional(),
  tracestate: z.string().optional(),
});

export type TraceContext = z.infer<typeof TraceContextSchema>;

export const EnvelopeSchema = z.object({
  version: z.string().default("1.0"),
  event_id: z.string().default(() => newULID()),
  event_type: z.string().min(1),
  timestamp: z.string().datetime().default(() => new Date().toISOString()),
  actor: ActorSchema,
  tenant_id: z.string().min(1),
  correlation_id: z.string().optional(),
  idempotency_key: z.string().optional(),
  priority: z.number().int().min(0).max(10).default(0),
  payload_ref: z.string().optional(),
  schema: z.string().optional(),
  trace: TraceContextSchema.optional(),
  payload: z.record(z.unknown()).optional(),
});

export type Envelope = z.infer<typeof EnvelopeSchema>;

/**
 * Create a new Envelope with auto-generated event_id and timestamp.
 */
export function createEnvelope(
  eventType: string,
  actor: Actor,
  tenantId: string,
  overrides?: Partial<Envelope>,
): Envelope {
  return EnvelopeSchema.parse({
    event_type: eventType,
    actor,
    tenant_id: tenantId,
    ...overrides,
  });
}
