/**
 * The optic nerve, face side: one TCP connection to the thalamus relay per Iris tab
 * (thalamus/src/relay.rs). The first line is the hello, built from the edge-verified
 * identity (hooks.server.ts) and the relay secret; after it the wire's newline-JSON lines
 * pass unchanged both ways. The secret never leaves this module.
 */
import { randomUUID } from 'node:crypto';
import { connect, type Socket } from 'node:net';
import { env } from '$env/dynamic/private';
import type { Identity } from '$lib/contracts';
import type { Link } from '$lib/iris/wire';

/** One line's cap, as the pupil's bridge (bridge.rs MAX_LINE). */
export const MAX_LINE = 1 << 20;
/** Open Iris tabs per person; the thalamus keeps only the newest anyway (relay.rs take_over). */
export const MAX_TABS = 4;

type Tab = { uid: string; sock: Socket };
const tabs = new Map<string, Tab>();

const relay = () => {
	const addr = env.NOS_THALAMUS_RELAY_ADDR ?? '';
	const secret = env.THALAMUS_RELAY_SECRET ?? '';
	const at = addr.lastIndexOf(':');
	const port = Number(addr.slice(at + 1));
	return at > 0 && port > 0 && secret ? { host: addr.slice(0, at), port, secret } : null;
};

export const configured = () => relay() !== null;

export const tabsOf = (uid: string) => [...tabs.values()].filter((t) => t.uid === uid).length;

/** The hello's who comes from the verified identity only, never from anything the browser sent. */
export const hello = (who: Identity, tab: string, secret: string) =>
	JSON.stringify({
		relay: 'face',
		secret,
		uid: who.uid,
		username: who.username,
		groups: who.groups,
		tab
	});

export type Sink = { line: (l: string) => void; link: (l: Link) => void };

/** Opens a tab for this person, or null when the relay is not configured or the person is at MAX_TABS. */
export function openTab(who: Identity, sink: Sink): { tab: string; close: () => void } | null {
	const r = relay();
	if (!r || !who.authenticated || tabsOf(who.uid) >= MAX_TABS) return null;
	const tab = randomUUID();
	const sock = connect({ host: r.host, port: r.port });
	tabs.set(tab, { uid: who.uid, sock });
	let buf = '';
	let why: string | null = null;
	sock.setEncoding('utf8');
	sock.on('connect', () => {
		sock.write(hello(who, tab, r.secret) + '\n');
		sink.link({ state: 'connected', reason: null });
	});
	sock.on('data', (chunk: string) => {
		buf += chunk;
		let nl;
		while ((nl = buf.indexOf('\n')) >= 0) {
			const line = buf.slice(0, nl);
			buf = buf.slice(nl + 1);
			if (line.trim()) sink.line(line);
		}
		if (buf.length > MAX_LINE) {
			why = 'the thalamus sent a line over 1 MiB';
			sock.destroy();
		}
	});
	// The error's message names host and port only; it never carries the hello.
	sock.on('error', (e) => (why ??= `the optic nerve failed: ${e.message}`));
	sock.on('close', () => {
		tabs.delete(tab);
		sink.link({
			state: 'closed',
			reason: why ?? 'the thalamus closed the link'
		});
	});
	return {
		tab,
		close: () => {
			why ??= 'the tab closed';
			sock.destroy();
		}
	};
}

/** One ToThalamus line onto a tab; only the person who opened it may drive it. */
export function sendLine(
	who: Identity,
	tab: string,
	line: string
): 'sent' | 'no tab' | 'not yours' {
	const t = tabs.get(tab);
	if (!t || t.sock.destroyed) return 'no tab';
	if (!who.authenticated || t.uid !== who.uid) return 'not yours';
	t.sock.write(line + '\n');
	return 'sent';
}

/**
 * A request this site's own page made. Sec-Fetch-Site and Origin are checked whenever the
 * browser sent them; `required` (a POST) refuses a request that carries neither.
 */
export function fromThisSite(request: Request, url: URL, required: boolean): boolean {
	const site = request.headers.get('sec-fetch-site');
	const origin = request.headers.get('origin');
	if (site !== null && site !== 'same-origin') return false;
	if (origin !== null && origin !== url.origin) return false;
	return !required || site !== null || origin !== null;
}

/** Test hook. */
export const _tabs = tabs;
