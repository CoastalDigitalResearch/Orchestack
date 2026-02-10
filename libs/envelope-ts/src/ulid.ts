/**
 * Minimal ULID implementation (Crockford Base32, monotonic within same ms).
 */
import { randomBytes } from "node:crypto";

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

let lastMs = 0;
const lastRnd = new Uint8Array(10);

/**
 * Generate a 26-character ULID string. Monotonic within the same millisecond.
 */
export function newULID(): string {
  const ms = Date.now();

  if (ms === lastMs) {
    // Increment random portion for monotonicity.
    for (let i = 9; i >= 0; i--) {
      lastRnd[i]++;
      if (lastRnd[i] !== 0) break;
    }
  } else {
    lastMs = ms;
    const rnd = randomBytes(10);
    lastRnd.set(rnd);
  }

  return encodeTime(ms) + encodeRandom(lastRnd);
}

function encodeTime(ms: number): string {
  let result = "";
  for (let i = 9; i >= 0; i--) {
    result = CROCKFORD[ms & 0x1f] + result;
    ms = Math.floor(ms / 32);
  }
  return result;
}

function encodeRandom(rnd: Uint8Array): string {
  // Encode 10 bytes (80 bits) into 16 base32 characters.
  // Process 5 bits at a time from the byte array.
  let result = "";
  let buffer = 0;
  let bitsLeft = 0;

  for (const byte of rnd) {
    buffer = (buffer << 8) | byte;
    bitsLeft += 8;
    while (bitsLeft >= 5) {
      bitsLeft -= 5;
      result += CROCKFORD[(buffer >>> bitsLeft) & 0x1f];
    }
  }

  return result;
}

/**
 * Check whether a string looks like a valid 26-character Crockford Base32 ULID.
 */
export function isValidULID(s: string): boolean {
  if (s.length !== 26) return false;
  const upper = s.toUpperCase();
  for (const c of upper) {
    if (!CROCKFORD.includes(c)) return false;
  }
  return true;
}
