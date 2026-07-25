import { describe, it, expect } from 'vitest';
import crypto from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { tokenEquals, bearerOf } from './tokens';

/**
 * LOCALLY AUTHORED (not a port) — KEAP ships no test for `server/tokens.ts`.
 *
 * `tokens.ts` is the one ported module whose failure mode is a security bug
 * rather than a drift rejection, and build sequence step 7 is the moment it
 * starts guarding a live socket. Two properties are pinned here, and both are
 * about the SHAPE of the comparison, not about it "working":
 *
 *  1. `crypto.timingSafeEqual` THROWS on a length mismatch. `tokenEquals` gets
 *     away with using it only because both operands are hashed to 32 bytes
 *     first. Compare the raw strings instead — the obvious "simplification" —
 *     and a token of the wrong length becomes a 500 where a right-length token
 *     is a 401. That difference is an oracle: it leaks the secret's length to
 *     an unauthenticated caller, and it does so through the error channel where
 *     nobody is looking for a leak. So the length case is asserted to RETURN
 *     FALSE, not merely to "not match".
 *
 *  2. The comparison is not `===`. Asserted structurally: the module source
 *     must contain `timingSafeEqual` and must not compare the two arguments
 *     with a plain equality operator. A behavioural test cannot see the
 *     difference — `===` passes every input/output assertion in this file —
 *     which is exactly why the port instruction singles this file out.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = readFileSync(path.join(HERE, 'tokens.ts'), 'utf8');

describe('tokenEquals', () => {
  it('accepts an exact match', () => {
    expect(tokenEquals('e2e-ro', 'e2e-ro')).toBe(true);
    expect(tokenEquals('', '')).toBe(true);
  });

  it('rejects a different token of the SAME length', () => {
    expect(tokenEquals('e2e-ro', 'e2e-rw')).toBe(false);
  });

  it('rejects a different length by RETURNING false, never by throwing', () => {
    // The property, stated as the negative it has to be: no input pair may make
    // this function raise. A raise here is a 500 on an unauthenticated route.
    expect(() => tokenEquals('a', 'a-much-longer-secret-value')).not.toThrow();
    expect(tokenEquals('a', 'a-much-longer-secret-value')).toBe(false);
    expect(tokenEquals('a-much-longer-secret-value', 'a')).toBe(false);
    expect(tokenEquals('', 'x')).toBe(false);

    // The mechanism, made explicit: raw timingSafeEqual on these two operands
    // is precisely what does throw. If this ever stops throwing, node changed
    // and the reasoning above needs rereading.
    expect(() =>
      crypto.timingSafeEqual(Buffer.from('a'), Buffer.from('a-much-longer-secret-value')),
    ).toThrow();
  });

  it('is case- and whitespace-exact', () => {
    expect(tokenEquals('Secret', 'secret')).toBe(false);
    expect(tokenEquals('secret ', 'secret')).toBe(false);
  });

  it('compares in constant time, structurally — never with ===', () => {
    expect(SOURCE).toContain('crypto.timingSafeEqual');
    expect(SOURCE).toContain("createHash('sha256')");
    expect(SOURCE).not.toMatch(/\ba\s*===\s*b\b/);
    expect(SOURCE).not.toMatch(/\breturn\s+a\s*==/);
  });
});

describe('bearerOf', () => {
  it('extracts the token after exactly "Bearer "', () => {
    expect(bearerOf('Bearer abc')).toBe('abc');
    expect(bearerOf('Bearer ')).toBe('');
  });

  it('returns null for anything that is not a Bearer header', () => {
    expect(bearerOf(undefined)).toBeNull();
    expect(bearerOf('')).toBeNull();
    expect(bearerOf('abc')).toBeNull();
    // The scheme is case-SENSITIVE here and the space is required. RFC 6750
    // says the scheme is case-insensitive, so a client sending `bearer x` is
    // refused by this implementation. That is KEAP's behaviour, ported
    // unchanged: this is pinned so the divergence is a recorded fact rather
    // than a surprise the first time a client lowercases its header.
    expect(bearerOf('bearer abc')).toBeNull();
    expect(bearerOf('Bearerabc')).toBeNull();
  });
});
