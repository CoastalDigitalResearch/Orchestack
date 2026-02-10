/**
 * Idempotency key generation per RFC-001.
 */
export function generateIdempotencyKey(
  tenantId: string,
  taskId: string,
  runAttempt: number,
  stepType: string,
  stepSeq: number,
): string {
  return `idem:${tenantId}:${taskId}:${runAttempt}:${stepType}:${stepSeq}`;
}
