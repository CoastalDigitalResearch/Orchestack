/**
 * W3C traceparent generation and parsing.
 */
import { randomBytes } from "node:crypto";

/**
 * Generate a new W3C traceparent header value.
 * Format: {version}-{trace-id}-{parent-id}-{trace-flags}
 */
export function newTraceParent(): string {
  const traceId = randomBytes(16).toString("hex");
  const parentId = randomBytes(8).toString("hex");
  return `00-${traceId}-${parentId}-01`;
}

/**
 * Parse a W3C traceparent header.
 * Returns { traceId, parentId, flags } or throws on invalid input.
 */
export function parseTraceParent(tp: string): {
  traceId: string;
  parentId: string;
  flags: string;
} {
  const parts = tp.split("-");
  if (parts.length !== 4) {
    throw new Error(`Invalid traceparent: expected 4 parts, got ${parts.length}`);
  }
  if (parts[0] !== "00") {
    throw new Error(`Unsupported traceparent version: ${parts[0]}`);
  }
  return { traceId: parts[1], parentId: parts[2], flags: parts[3] };
}
