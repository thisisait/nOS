import { createServer, type Server, type Socket } from 'node:net';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * The optic nerve's face half (iris-face-app): the hello carries the edge-verified person,
 * never the browser's word; a tab is driven only by whom it was opened for; a cross-site or
 * non-JSON POST is refused (SvelteKit's CSRF check covers form content-types only).
 */
const ENV = vi.hoisted(() => ({}) as Record<string, string>);
vi.mock('$env/dynamic/private', () => ({ env: ENV }));

import { ANON, type Identity } from '$lib/contracts';
import { GET } from '../../routes/bff/iris/stream/+server';
import { POST } from '../../routes/bff/iris/send/+server';
import { _tabs, MAX_TABS } from './thalamus';

const SECRET = 'test-relay-secret-not-a-real-credential';
const ORIGIN = 'https://face.test';
const ALICE: Identity = {
	uid: 'alice',
	username: 'alice',
	email: 'alice@example.test',
	groups: ['nos-users'],
	authenticated: true
};
const BOB: Identity = { ...ALICE, uid: 'bob', username: 'bob' };

// A fake thalamus relay: records each connection's lines, and can answer.
let server: Server;
let peers: { sock: Socket; lines: string[] }[] = [];
beforeEach(async () => {
	peers = [];
	server = createServer((sock) => {
		const p = { sock, lines: [] as string[] };
		peers.push(p);
		let buf = '';
		sock.setEncoding('utf8');
		sock.on('data', (c: string) => {
			buf += c;
			let nl;
			while ((nl = buf.indexOf('\n')) >= 0) {
				p.lines.push(buf.slice(0, nl));
				buf = buf.slice(nl + 1);
			}
		});
	});
	await new Promise<void>((ok) => server.listen(0, '127.0.0.1', ok));
	const addr = server.address() as { port: number };
	for (const k of Object.keys(ENV)) delete ENV[k];
	ENV.NOS_THALAMUS_RELAY_ADDR = `127.0.0.1:${addr.port}`;
	ENV.THALAMUS_RELAY_SECRET = SECRET;
});
afterEach(async () => {
	for (const t of _tabs.values()) t.sock.destroy();
	_tabs.clear();
	for (const p of peers) p.sock.destroy();
	await new Promise((ok) => server.close(ok));
});

// The connection by its hello's tab, not by arrival order: under load peers[0] was another tab's (2026-10-18).
const peerOf = (tab: string) => peers.find((p) => p.lines[0] && JSON.parse(p.lines[0]).tab === tab);

const until = async (ok: () => boolean) => {
	// 5 s, not 1: failed once at 1 s while the pytest lanes loaded the host (2026-10-18).
	for (let i = 0; i < 1000 && !ok(); i++) await new Promise((r) => setTimeout(r, 5));
	expect(ok()).toBe(true);
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Ev = any;
const ev = (who: Identity, request: Request): Ev => ({
	request,
	url: new URL(request.url),
	locals: { identity: who }
});
const refused = async (p: () => unknown) => {
	try {
		await p();
	} catch (e) {
		return (e as { status: number }).status;
	}
	return 0;
};

/** Opens a stream as `who` and reads its events as text. */
async function stream(who: Identity, headers: Record<string, string> = {}) {
	const res = (await GET(
		ev(who, new Request(`${ORIGIN}/bff/iris/stream`, { headers: { ...headers } }))
	)) as Response;
	const reader = res.body!.getReader();
	const dec = new TextDecoder();
	const s = { res, text: '', tab: '', done: false };
	(async () => {
		for (;;) {
			const { value, done } = await reader.read();
			if (done) return void (s.done = true);
			s.text += dec.decode(value);
		}
	})();
	await until(() => /event: tab\ndata: (.*)\n/.test(s.text));
	s.tab = JSON.parse(/event: tab\ndata: (.*)\n/.exec(s.text)![1]).tab;
	return Object.assign(s, { cancel: () => reader.cancel() });
}

const post = (who: Identity, tab: string, body: string, headers: Record<string, string> = {}) =>
	POST(
		ev(
			who,
			new Request(`${ORIGIN}/bff/iris/send`, {
				method: 'POST',
				body,
				headers: {
					origin: ORIGIN,
					'sec-fetch-site': 'same-origin',
					'content-type': 'application/json',
					'x-iris-tab': tab,
					...headers
				}
			})
		)
	) as Promise<Response>;

describe('bff/iris/stream', () => {
	it('refuses the anonymous', async () => {
		expect(await refused(() => GET(ev(ANON, new Request(`${ORIGIN}/bff/iris/stream`))))).toBe(401);
	});

	it('refuses a cross-site stream (a take-over from another site)', async () => {
		const r = new Request(`${ORIGIN}/bff/iris/stream`, {
			headers: { 'sec-fetch-site': 'cross-site' }
		});
		expect(await refused(() => GET(ev(ALICE, r)))).toBe(403);
		expect(peers).toHaveLength(0);
	});

	it('says so when no relay is configured, and opens nothing', async () => {
		delete ENV.THALAMUS_RELAY_SECRET;
		expect(await refused(() => GET(ev(ALICE, new Request(`${ORIGIN}/bff/iris/stream`))))).toBe(503);
	});

	it('the hello carries the verified identity, whatever the browser asserted', async () => {
		const s = await stream(ALICE, {
			'x-authentik-uid': 'root',
			'x-authentik-username': 'root',
			'x-authentik-groups': 'nos-admins'
		});
		expect(s.res.headers.get('content-type')).toBe('text/event-stream');
		await until(() => peers[0]?.lines.length === 1);
		const hello = JSON.parse(peers[0].lines[0]);
		expect(hello).toEqual({
			relay: 'face',
			secret: SECRET,
			uid: 'alice',
			username: 'alice',
			groups: ['nos-users'],
			tab: s.tab
		});
		await until(() => s.text.includes('"state":"connected"'));
		expect(s.text).not.toContain(SECRET);
	});

	it('one SSE event per ToShell line, unchanged; the secret never reaches the browser', async () => {
		const s = await stream(ALICE);
		await until(() => peers.length === 1);
		const line = '{"t":"session","session":"s1"}';
		peers[0].sock.write(`${line}\n{"t":"said","text":"hi"}\n`);
		await until(() => s.text.includes('"said"'));
		expect(s.text).toContain(`data: ${line}\n\n`);
		expect(s.text).not.toContain(SECRET);
	});

	it('the thalamus closing the link closes the stream with a link event', async () => {
		const s = await stream(ALICE);
		await until(() => peers.length === 1);
		peers[0].sock.end();
		await until(() => s.done);
		expect(s.text).toMatch(/event: link\ndata: \{"state":"closed"/);
		expect(_tabs.size).toBe(0);
	});

	it('the client going closes the TCP connection', async () => {
		const s = await stream(ALICE);
		await until(() => peers.length === 1);
		let closed = false;
		peers[0].sock.on('close', () => (closed = true));
		await s.cancel();
		await until(() => closed);
	});

	it('caps the tabs one person holds open', async () => {
		for (let i = 0; i < MAX_TABS; i++) await stream(ALICE);
		expect(await refused(() => GET(ev(ALICE, new Request(`${ORIGIN}/bff/iris/stream`))))).toBe(429);
		await stream(BOB);
	});
});

describe('bff/iris/send', () => {
	it('same-origin JSON is forwarded as one line equal to the body', async () => {
		const s = await stream(ALICE);
		const body = '{"t":"turn","session":null,"text":"hello"}';
		expect((await post(ALICE, s.tab, body)).status).toBe(204);
		await until(() => peerOf(s.tab)?.lines.length === 2);
		expect(peerOf(s.tab)!.lines[1]).toBe(body);
	});

	it('a pretty-printed body still travels as one line', async () => {
		const s = await stream(ALICE);
		await post(ALICE, s.tab, '{\n  "t": "resume"\n}');
		await until(() => peerOf(s.tab)?.lines.length === 2);
		expect(peerOf(s.tab)!.lines[1]).toBe('{"t":"resume"}');
	});

	it.each([
		['a foreign Origin', { origin: 'https://evil.test', 'sec-fetch-site': '' }],
		['a cross-site fetch', { 'sec-fetch-site': 'cross-site' }],
		['text/plain', { 'content-type': 'text/plain' }],
		['a form post', { 'content-type': 'application/x-www-form-urlencoded' }]
	])('%s is refused with 403 and forwards nothing', async (_, h) => {
		const s = await stream(ALICE);
		const req = new Request(`${ORIGIN}/bff/iris/send`, {
			method: 'POST',
			body: '{"t":"resume"}',
			headers: {
				origin: ORIGIN,
				'sec-fetch-site': 'same-origin',
				'content-type': 'application/json',
				'x-iris-tab': s.tab
			}
		});
		// An empty value is a header the browser did not send.
		for (const [k, v] of Object.entries(h as Record<string, string>))
			if (v) req.headers.set(k, v);
			else req.headers.delete(k);
		expect(await refused(() => POST(ev(ALICE, req)))).toBe(403);
		await new Promise((r) => setTimeout(r, 20));
		expect(peers[0].lines).toHaveLength(1);
	});

	it('a request with neither Origin nor Sec-Fetch-Site is refused', async () => {
		const s = await stream(ALICE);
		const req = new Request(`${ORIGIN}/bff/iris/send`, {
			method: 'POST',
			body: '{"t":"resume"}',
			headers: { 'content-type': 'application/json', 'x-iris-tab': s.tab }
		});
		expect(await refused(() => POST(ev(ALICE, req)))).toBe(403);
	});

	it('refuses the anonymous', async () => {
		expect(await refused(() => post(ANON, 'x', '{"t":"resume"}'))).toBe(401);
	});

	it("a tab cannot be driven by another person's identity", async () => {
		const s = await stream(ALICE);
		expect(await refused(() => post(BOB, s.tab, '{"t":"resume"}'))).toBe(403);
		await new Promise((r) => setTimeout(r, 20));
		expect(peers[0].lines).toHaveLength(1);
	});

	it('an unknown tab is a conflict, not a send', async () => {
		expect(await refused(() => post(ALICE, 'no-such-tab', '{"t":"resume"}'))).toBe(409);
	});

	it('a body over 1 MiB, or not one JSON object, is refused', async () => {
		const s = await stream(ALICE);
		const big = JSON.stringify({ t: 'turn', text: 'x'.repeat(1 << 20) });
		expect(await refused(() => post(ALICE, s.tab, big))).toBe(413);
		expect(await refused(() => post(ALICE, s.tab, 'not json'))).toBe(400);
		expect(await refused(() => post(ALICE, s.tab, '[1]'))).toBe(400);
	});
});
