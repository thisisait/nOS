import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * The face calls KEAP AS THE PERSON (keap-door increment 2). Before this, every
 * table read/write went to /agent/v1 with the estate RO/RW bearers, so KEAP saw
 * no person and stamped rows `agent:unknown`. Gate:
 * tests/anatomy/test_end_user_services_hold_no_estate_token.py (face half).
 */
const ENV = vi.hoisted(() => ({}) as Record<string, string>);
vi.mock('$env/dynamic/private', () => ({ env: ENV }));

import {
	keapTableRows,
	keapTableDef,
	keapListTables,
	keapUpsertRow,
	keapCreateTable,
	UpstreamError
} from './upstream';
import { ANON, type Identity } from '$lib/contracts';

const ALICE: Identity = {
	uid: 'alice',
	username: 'alice',
	email: 'alice@example.test',
	name: 'Alice A',
	groups: ['nos-managers', 'nos-users'],
	authenticated: true
};
const SECRET = 'test-proxy-secret-not-a-real-credential';

type Call = { url: string; init: RequestInit };
let calls: Call[] = [];
let replies: unknown[] = [];

beforeEach(() => {
	for (const k of Object.keys(ENV)) delete ENV[k];
	ENV.NOS_KEAP_TABLES_URL = 'http://keap.test/api/tables';
	ENV.KEAP_PROXY_SHARED_SECRET = SECRET;
	// Stray estate bearers in the env must never reach the wire.
	ENV.NOS_KEAP_API_TOKEN = 'estate-ro';
	ENV.NOS_KEAP_API_TOKEN_RW = 'estate-rw';
	calls = [];
	replies = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: URL | string, init: RequestInit = {}) => {
			calls.push({ url: String(url), init });
			const body = replies.length ? replies.shift() : { success: true, data: {} };
			return new Response(JSON.stringify(body), { status: 200 });
		})
	);
});
afterEach(() => vi.unstubAllGlobals());

const headersOf = (c: Call) => new Headers(c.init.headers as HeadersInit);

function expectAsAlice(c: Call) {
	const h = headersOf(c);
	expect(h.get('authorization')).toBeNull();
	expect(h.get('x-keap-proxy-secret')).toBe(SECRET);
	expect(h.get('x-authentik-username')).toBe('alice');
	expect(h.get('x-authentik-email')).toBe('alice@example.test');
	expect(h.get('x-authentik-name')).toBe('Alice A');
	expect(h.get('x-authentik-groups')).toBe('nos-managers,nos-users');
	expect(c.url).not.toContain('/agent/v1');
}

describe('KEAP tables via the human door', () => {
	it('reads rows as the person, flattened, following the cursor', async () => {
		replies = [
			{ success: true, data: { rows: [{ id: 'r1', values: { slug: 'a' } }], nextCursor: '1' } },
			{ success: true, data: { rows: [{ id: 'r2', values: { slug: 'b' }, sharing: { x: 1 } }] } }
		];
		const out = (await keapTableRows('face-layouts', ALICE)) as { rows: unknown[] };
		expect(calls).toHaveLength(2);
		calls.forEach(expectAsAlice);
		expect(calls[0].url).toBe('http://keap.test/api/tables/face-layouts/rows?limit=500');
		expect(new URL(calls[1].url).searchParams.get('cursor')).toBe('1');
		expect(out.rows).toEqual([
			{ slug: 'a', __id: 'r1' },
			{ slug: 'b', __id: 'r2', __sharing: { x: 1 } }
		]);
	});

	it('writes a row as the person in the human-door body shape', async () => {
		replies = [{ success: true, data: { id: 'a', values: { slug: 'a', name: 'A' } } }];
		const out = await keapUpsertRow('face-layouts', { __id: 'a', slug: 'a', name: 'A' }, ALICE);
		expectAsAlice(calls[0]);
		expect(calls[0].init.method).toBe('POST');
		expect(JSON.parse(String(calls[0].init.body))).toEqual({
			id: 'a',
			values: { slug: 'a', name: 'A' }
		});
		expect(out).toEqual({ slug: 'a', name: 'A', __id: 'a' });
	});

	it('def, list and create carry the person too', async () => {
		await keapTableDef('roadmap', ALICE);
		await keapListTables(ALICE);
		await keapCreateTable({ title: 'T', schema: { columns: [] } }, ALICE);
		expect(calls).toHaveLength(3);
		calls.forEach(expectAsAlice);
	});

	it('refuses without an edge-trusted identity: no anonymous call', async () => {
		const tries = [
			() => keapTableRows('x', ANON),
			() => keapTableDef('x', ANON),
			() => keapListTables(ANON),
			() => keapUpsertRow('x', { slug: 'a' }, ANON),
			() => keapCreateTable({ title: 'T' }, ANON)
		];
		for (const t of tries) await expect(t()).rejects.toBeInstanceOf(UpstreamError);
		expect(calls).toHaveLength(0);
	});
});

describe('bff/tables POST takes the person from locals, never the browser', () => {
	it('a spoofed X-Authentik-* on the browser request does not reach KEAP', async () => {
		const { POST } = await import('../../routes/bff/tables/+server');
		replies = [{ success: true, data: { id: 'a', values: { slug: 'a' } } }];
		const request = new Request('http://face.test/bff/tables', {
			method: 'POST',
			headers: { 'x-authentik-username': 'mallory', 'x-authentik-groups': 'nos-admins' },
			body: JSON.stringify({ op: 'upsertRow', slug: 'face-layouts', row: { slug: 'a' } })
		});
		const res = await POST({ request, locals: { identity: ALICE } } as never);
		expect(res.status).toBe(200);
		expect(calls).toHaveLength(1);
		expectAsAlice(calls[0]);
	});
});
