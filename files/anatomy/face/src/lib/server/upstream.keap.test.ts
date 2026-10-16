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
// An admin, so the 200 the stub gives a write is what live KEAP would give.
const ROOT: Identity = { ...ALICE, uid: 'root', username: 'root', groups: ['nos-admins'] };
const SECRET = 'test-proxy-secret-not-a-real-credential';

type Call = { url: string; init: RequestInit };
let calls: Call[] = [];
let replies: unknown[] = [];
let status = 200;

beforeEach(() => {
	for (const k of Object.keys(ENV)) delete ENV[k];
	ENV.NOS_KEAP_TABLES_URL = 'http://keap.test/api/tables';
	ENV.KEAP_PROXY_SHARED_SECRET = SECRET;
	// Stray estate bearers in the env must never reach the wire.
	ENV.NOS_KEAP_API_TOKEN = 'estate-ro';
	ENV.NOS_KEAP_API_TOKEN_RW = 'estate-rw';
	calls = [];
	replies = [];
	status = 200;
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: URL | string, init: RequestInit = {}) => {
			calls.push({ url: String(url), init });
			const body = replies.length ? replies.shift() : { success: true, data: {} };
			return new Response(JSON.stringify(body), { status });
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

	it('refuses without the proxy secret: no call KEAP would have to reject', async () => {
		delete ENV.KEAP_PROXY_SHARED_SECRET;
		const tries = [
			() => keapTableRows('x', ALICE),
			() => keapTableDef('x', ALICE),
			() => keapListTables(ALICE),
			() => keapUpsertRow('x', { slug: 'a' }, ALICE),
			() => keapCreateTable({ title: 'T' }, ALICE)
		];
		for (const t of tries) await expect(t()).rejects.toBeInstanceOf(UpstreamError);
		expect(calls).toHaveLength(0);
	});

	it('create keeps the typed slug: one id per person + slug, never a fresh one', async () => {
		await keapCreateTable({ slug: 'budget', title: 'B' }, ALICE);
		await keapCreateTable({ slug: 'budget', title: 'B' }, ALICE);
		await keapCreateTable({ slug: 'budget', title: 'B' }, ROOT);
		const ids = calls.map((c) => JSON.parse(String(c.init.body)).id);
		expect(ids[0]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
		expect(ids[1]).toBe(ids[0]);
		expect(ids[2]).not.toBe(ids[0]);
	});
	it('a second submit of one slug reuses the table KEAP already holds', async () => {
		// A tiny KEAP: POST refuses a duplicate id (400, as routes.ts does), GET reads one.
		const store = new Map<string, unknown>();
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: URL | string, init: RequestInit = {}) => {
				const id = String(url).split('/api/tables/')[1];
				if (init.method === 'POST') {
					const t = JSON.parse(String(init.body));
					if (store.has(t.id)) return new Response('{"success":false}', { status: 400 });
					store.set(t.id, t);
					return new Response(JSON.stringify({ success: true, data: t }));
				}
				const t = id && store.get(decodeURIComponent(id));
				return t
					? new Response(JSON.stringify({ success: true, data: t }))
					: new Response('{}', { status: 404 });
			})
		);
		const a = (await keapCreateTable({ slug: 'budget', title: 'B' }, ALICE)) as {
			data: { id: string };
		};
		const b = (await keapCreateTable({ slug: 'budget', title: 'B' }, ALICE)) as {
			data: { id: string };
		};
		expect(store.size).toBe(1);
		expect(b.data.id).toBe(a.data.id);
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
		const res = await POST({ request, locals: { identity: ROOT } } as never);
		expect(res.status).toBe(200);
		expect(calls).toHaveLength(1);
		const h = headersOf(calls[0]);
		expect(h.get('x-authentik-username')).toBe('root');
		expect(h.get('x-authentik-groups')).toBe('nos-admins');
	});

	// Live KEAP (rbac.ts canWriteRowAs) refuses a manager who is neither owner,
	// admin nor write-granted; the face must surface that 403, not a success.
	it("KEAP's 403 to a non-owner manager reaches the browser as 403", async () => {
		const { POST } = await import('../../routes/bff/tables/+server');
		status = 403;
		replies = [{ success: false, error: 'no write access to this table' }];
		const request = new Request('http://face.test/bff/tables', {
			method: 'POST',
			body: JSON.stringify({ op: 'upsertRow', slug: 'face-layouts', row: { slug: 'a' } })
		});
		await expect(POST({ request, locals: { identity: ALICE } } as never)).rejects.toMatchObject({
			status: 403
		});
		expectAsAlice(calls[0]);
	});
});
