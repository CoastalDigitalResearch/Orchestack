/**
 * Envelope validation rules.
 */
import type { Envelope } from "./envelope.js";

export const VALID_ACTOR_TYPES = new Set(["user", "agent", "system", "connector"]);
export const VALID_VERSIONS = new Set(["1.0"]);

/**
 * Validate an envelope, returning a list of errors (empty if valid).
 */
export function validateEnvelope(envelope: Envelope): string[] {
  const errors: string[] = [];

  if (!VALID_VERSIONS.has(envelope.version)) {
    errors.push(`Invalid version: ${envelope.version}`);
  }
  if (!envelope.event_id) {
    errors.push("event_id is required");
  }
  if (!envelope.event_type) {
    errors.push("event_type is required");
  }
  if (!envelope.tenant_id) {
    errors.push("tenant_id is required");
  }
  if (!VALID_ACTOR_TYPES.has(envelope.actor.type)) {
    errors.push(`Invalid actor type: ${envelope.actor.type}`);
  }
  if (!envelope.actor.id) {
    errors.push("actor.id is required");
  }
  if (envelope.priority < 0 || envelope.priority > 10) {
    errors.push(`Priority must be 0-10, got ${envelope.priority}`);
  }

  return errors;
}
