/** BFF · Iris stream — one SSE stream is one relay tab (lib/server/thalamus.ts).
 *  First event `tab` names it (POST bff/iris/send carries it back); `link` events say the
 *  connection's state; every other event is one ToShell line, unchanged. */
import { error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { configured, fromThisSite, openTab } from '$lib/server/thalamus';

const HEARTBEAT_MS = 15_000;

export const GET: RequestHandler = ({ request, url, locals }) => {
	if (!locals.identity.authenticated) error(401, 'unauthenticated');
	if (!fromThisSite(request, url, false)) error(403, 'not from this site');
	if (!configured()) error(503, 'the optic nerve is not configured (no thalamus relay)');

	const enc = new TextEncoder();
	let ctl: ReadableStreamDefaultController<Uint8Array> | null = null;
	let beat: ReturnType<typeof setInterval> | undefined;
	const put = (s: string) => {
		try {
			ctl?.enqueue(enc.encode(s));
		} catch {
			// the client already went
		}
	};
	const end = () => {
		clearInterval(beat);
		try {
			ctl?.close();
		} catch {
			// already closed
		}
	};
	const tab = openTab(locals.identity, {
		line: (l) => put(`data: ${l}\n\n`),
		link: (l) => {
			put(`event: link\ndata: ${JSON.stringify(l)}\n\n`);
			if (l.state === 'closed') end();
		}
	});
	if (!tab) error(429, 'too many Iris tabs open');

	const body = new ReadableStream<Uint8Array>({
		start(c) {
			ctl = c;
			put(`event: tab\ndata: ${JSON.stringify({ tab: tab.tab })}\n\n`);
			beat = setInterval(() => put(': beat\n\n'), HEARTBEAT_MS);
		},
		cancel() {
			clearInterval(beat);
			tab.close();
		}
	});
	return new Response(body, {
		headers: {
			'content-type': 'text/event-stream',
			'cache-control': 'no-store',
			'x-accel-buffering': 'no'
		}
	});
};
