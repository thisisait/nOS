// @vitest-environment happy-dom
// The face's Iris transport on a fake EventSource and fetch: the stream's tab rides every
// send, ToShell lines reach Iris unchanged, a server-closed link stays closed.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webTransport } from './transport.web';
import type { Link, ToShell } from './wire';

class FakeES {
	static last: FakeES | null = null;
	static CLOSED = 2;
	readyState = 1;
	closed = false;
	onmessage: ((e: MessageEvent) => void) | null = null;
	onerror: (() => void) | null = null;
	ls: Record<string, ((e: MessageEvent) => void)[]> = {};
	constructor(public url: string) {
		FakeES.last = this;
	}
	addEventListener(t: string, cb: (e: MessageEvent) => void) {
		(this.ls[t] ??= []).push(cb);
	}
	close() {
		this.closed = true;
		this.readyState = 2;
	}
	emit(t: string, data: unknown) {
		const e = { data: JSON.stringify(data) } as MessageEvent;
		if (t === 'message') this.onmessage?.(e);
		else this.ls[t]?.forEach((cb) => cb(e));
	}
}

let calls: { url: string; init: RequestInit }[] = [];
let reply = () => new Response(null, { status: 204 });
beforeEach(() => {
	calls = [];
	reply = () => new Response(null, { status: 204 });
	vi.stubGlobal('EventSource', FakeES);
	vi.stubGlobal('fetch', async (url: string | URL, init: RequestInit = {}) => {
		calls.push({ url: String(url), init });
		return reply();
	});
});
afterEach(() => vi.unstubAllGlobals());

async function opened() {
	const t = webTransport();
	const shell: ToShell[] = [];
	const links: Link[] = [];
	await t.onShell((m) => shell.push(m));
	await t.onLink((l) => links.push(l));
	await t.connect();
	const es = FakeES.last!;
	es.emit('tab', { tab: 'tab-1' });
	es.emit('link', { state: 'connected', reason: null });
	return { t, es, shell, links };
}

describe('webTransport', () => {
	it('streams from the BFF and hands Iris each line as it came', async () => {
		const { es, shell, links } = await opened();
		expect(es.url).toBe('/bff/iris/stream');
		es.emit('message', { t: 'session', session: 's1' });
		expect(shell).toEqual([{ t: 'session', session: 's1' }]);
		expect(links).toEqual([{ state: 'connected', reason: null }]);
	});

	it('posts one JSON message carrying the tab the stream named', async () => {
		const { t } = await opened();
		await t.send({ t: 'resume' });
		expect(calls).toHaveLength(1);
		expect(calls[0].url).toBe('/bff/iris/send');
		expect(calls[0].init.method).toBe('POST');
		const h = calls[0].init.headers as Record<string, string>;
		expect(h['content-type']).toBe('application/json');
		expect(h['x-iris-tab']).toBe('tab-1');
		expect(JSON.parse(calls[0].init.body as string)).toEqual({ t: 'resume' });
	});

	it('refuses to send before the stream named a tab, and says a refused send', async () => {
		const t = webTransport();
		await t.connect();
		await expect(t.send({ t: 'resume' })).rejects.toThrow('not connected');
		FakeES.last!.emit('tab', { tab: 'tab-2' });
		reply = () => new Response('not your tab', { status: 403 });
		await expect(t.send({ t: 'resume' })).rejects.toThrow('403');
	});

	it('a link the thalamus closed stays closed: no ping-pong with the tab that took over', async () => {
		const { t, es, links } = await opened();
		es.emit('link', { state: 'closed', reason: 'opened in another tab' });
		expect(es.closed).toBe(true);
		expect(links.at(-1)).toEqual({ state: 'closed', reason: 'opened in another tab' });
		await expect(t.send({ t: 'resume' })).rejects.toThrow('not connected');
	});

	it('a dropped stream says so; a refused one is closed', async () => {
		const { es, links } = await opened();
		es.onerror!();
		expect(links.at(-1)?.state).toBe('closed');
		expect(es.closed).toBe(false);
		es.readyState = FakeES.CLOSED;
		es.onerror!();
		expect(es.closed).toBe(true);
	});

	it('the layout cache is the person user-state app.iris; a garbled one is an empty layout', async () => {
		reply = () => Response.json({ value: { nope: 1 } });
		const t = webTransport();
		const l = await t.loadLayout();
		expect(l.version).toBe(3);
		expect(calls[0].url).toContain('ns=app.iris');
		reply = () => Response.json({ ok: true });
		await t.saveLayout(l);
		expect(JSON.parse(calls[1].init.body as string)).toMatchObject({
			op: 'set',
			ns: 'app.iris',
			key: 'layout'
		});
	});

	it('exports a CSV as a browser download', async () => {
		const clicked: string[] = [];
		const orig = HTMLAnchorElement.prototype.click;
		HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
			clicked.push(this.download);
		};
		try {
			const said = await webTransport().exportCsv('orders', 'a,b\n1,2\n');
			expect(clicked).toEqual(['orders.csv']);
			expect(said).toContain('orders.csv');
		} finally {
			HTMLAnchorElement.prototype.click = orig;
		}
	});
});
