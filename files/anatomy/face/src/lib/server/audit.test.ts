import { describe, expect, it } from 'vitest';
import { createHmac } from 'node:crypto';
import { signEvent } from './audit';

/**
 * D5 table-write-audit — RETRO-RED: before this commit `$lib/server/audit.ts`
 * did not exist and bff/tables' upsertRow path had a `// TODO audit` and no
 * HMAC signer at all — importing `signEvent` here threw a module-not-found.
 *
 * The reference computation below is Bone's `verify_hmac`
 * (files/anatomy/bone/events.py): `hmac_sha256(secret, ts + "." + body).hexdigest()`,
 * with NO `sha256=` prefix required (Bone accepts either). Reproducing that
 * math independently (not by calling signEvent twice) is the point — a bug
 * that flips a separator or forgets sort_keys would pass a self-comparison.
 */
function referenceSignature(secret: string, ts: string, body: string): string {
	return createHmac('sha256', secret).update(`${ts}.${body}`).digest('hex');
}

describe('signEvent', () => {
	const SECRET = 'test-hmac-secret-not-a-real-credential';

	it('produces a canonical, sorted-key JSON body', () => {
		const { body } = signEvent(SECRET, { type: 'table.upsert', run_id: 'r1' }, 1_700_000_000);
		// sort_keys: run_id before type, alphabetically — and no whitespace.
		expect(body).toBe('{"run_id":"r1","type":"table.upsert"}');
	});

	it('sorts nested object keys too, recursively', () => {
		const { body } = signEvent(SECRET, { result: { slug: 's', row_id: 'r' } }, 1_700_000_000);
		expect(body).toBe('{"result":{"row_id":"r","slug":"s"}}');
	});

	it('matches an independently-computed HMAC over ts + "." + body', () => {
		const { body, headers } = signEvent(SECRET, { a: 1 }, 1_700_000_000);
		expect(headers['X-Wing-Timestamp']).toBe('1700000000');
		expect(headers['X-Wing-Signature']).toBe(referenceSignature(SECRET, '1700000000', body));
	});

	it('a different secret produces a different signature (not a constant stub)', () => {
		const a = signEvent('secret-a', { x: 1 }, 1_700_000_000);
		const b = signEvent('secret-b', { x: 1 }, 1_700_000_000);
		expect(a.headers['X-Wing-Signature']).not.toBe(b.headers['X-Wing-Signature']);
	});

	it('carries Content-Type: application/json', () => {
		const { headers } = signEvent(SECRET, {});
		expect(headers['Content-Type']).toBe('application/json');
	});
});
