import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * An immune verdict (row immune-verdicts-write-path) is the operator's face edit: Tier 1 only,
 * `why` capped at 300, refused without an audit trail, and one audit event naming who, cell and
 * verdict, never the why. Drives the real POST handler, upstream and audit; only fetch is stubbed.
 */
const ENV = vi.hoisted(() => ({}) as Record<string, string>);
vi.mock('$app/env/private', () => new Proxy(ENV, { has: () => true }));

import { POST } from '../../routes/bff/tables/+server';
import type { Identity } from '$lib/contracts';

const OPERATOR: Identity = {
	uid: 'op',
	username: 'op',
	email: 'op@example.test',
	groups: ['nos-admins'],
	authenticated: true
};
const MANAGER: Identity = { ...OPERATOR, uid: 'mgr', username: 'mgr', groups: ['nos-managers'] };
const WHY = 'the scan matched a vendored test fixture, not a live key';
const ROW = {
	slug: 'v1',
	occurred_at: 1,
	cell: 'gitleaks:nightly-scan',
	firing: 'run-7',
	verdict: 'false-alarm',
	why: WHY,
	judged_by: 'op'
};

type Call = { url: string; body: string };
let calls: Call[] = [];

beforeEach(() => {
	for (const k of Object.keys(ENV)) delete ENV[k];
	ENV.NOS_KEAP_TABLES_URL = 'http://keap.test/api/tables';
	ENV.KEAP_PROXY_SHARED_SECRET = 'test-proxy-secret-not-a-real-credential';
	ENV.WING_EVENTS_HMAC_SECRET = 'test-hmac-secret-not-a-real-credential';
	ENV.NOS_BONE_EVENTS_URL = 'http://bone.test/api/v1/events';
	calls = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: URL | string, init: RequestInit = {}) => {
			calls.push({ url: String(url), body: String(init.body ?? '') });
			return new Response(JSON.stringify({ success: true, data: { id: 'v1' } }), { status: 200 });
		})
	);
});
afterEach(() => vi.unstubAllGlobals());

const post = (who: Identity, row: Record<string, unknown>, slug = 'immune-verdicts') =>
	POST({
		request: new Request('http://face.test/bff/tables', {
			method: 'POST',
			body: JSON.stringify({ op: 'upsertRow', slug, row })
		}),
		locals: { identity: who }
	} as unknown as Parameters<typeof POST>[0]);
const events = () => calls.filter((c) => c.url.startsWith('http://bone.test/'));
const writes = () => calls.filter((c) => c.url.startsWith('http://keap.test/'));

describe('immune verdicts through the face', () => {
	it('the operator writes one, and one audit event names who, cell and verdict, never the why', async () => {
		const res = await post(OPERATOR, ROW);
		expect(res.status).toBe(200);
		expect(writes()).toHaveLength(1);
		expect(events()).toHaveLength(1);
		const ev = JSON.parse(events()[0].body);
		expect(ev).toMatchObject({ type: 'table.upsert', actor_id: 'op' });
		expect(ev.result).toEqual({
			slug: 'immune-verdicts',
			row_id: 'v1',
			cell: 'gitleaks:nightly-scan',
			verdict: 'false-alarm'
		});
		expect(events()[0].body).not.toContain(WHY);
	});

	it('a manager is refused below Tier 1, nothing written or audited', async () => {
		await expect(post(MANAGER, ROW)).rejects.toMatchObject({ status: 403 });
		expect(calls).toHaveLength(0);
	});

	it('a 301-character why is refused with a message naming the cap; 300 lands', async () => {
		await expect(post(OPERATOR, { ...ROW, why: 'x'.repeat(301) })).rejects.toMatchObject({
			status: 400,
			body: { message: expect.stringContaining('300') }
		});
		expect(calls).toHaveLength(0);
		expect((await post(OPERATOR, { ...ROW, why: 'x'.repeat(300) })).status).toBe(200);
	});

	it('without the audit secret a verdict is refused, other tables still write', async () => {
		delete ENV.WING_EVENTS_HMAC_SECRET;
		await expect(post(OPERATOR, ROW)).rejects.toMatchObject({ status: 503 });
		expect(calls).toHaveLength(0);
		expect((await post(MANAGER, { slug: 'x', name: 'y' }, 'face-layouts')).status).toBe(200);
	});
});
