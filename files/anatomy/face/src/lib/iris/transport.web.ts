// Iris's transport in the face: the BFF's optic nerve (routes/bff/iris). The stream's first
// event names the tab; every send carries it back, and the BFF lets only its opener drive it.
// The thalamus's workspace messages ride `send` (Iris says them); the layout calls are the
// offline cache in the person's user-state, namespace app.iris.
import { usGet, usSet } from '$lib/api/userstate';
import type { Transport } from './transport';
import type { Link, ToShell } from './wire';
import { empty, type Layout } from './workspace';

const NS = 'app.iris';

export function webTransport(base = '/bff/iris'): Transport & { close(): void } {
	const shell = new Set<(m: ToShell) => void>();
	const link = new Set<(l: Link) => void>();
	const say = (l: Link) => link.forEach((cb) => cb(l));
	let es: EventSource | null = null;
	let tab: string | null = null;

	const close = () => {
		es?.close();
		es = null;
		tab = null;
	};
	return {
		async connect() {
			close();
			const s = new EventSource(`${base}/stream`);
			es = s;
			s.addEventListener('tab', (e) => (tab = JSON.parse((e as MessageEvent).data).tab));
			s.addEventListener('link', (e) => {
				const l = JSON.parse((e as MessageEvent).data) as Link;
				// ponytail: a closed link stays closed (no ping-pong when another tab took over);
				// reopening the app reconnects. Retry-with-reason when the thalamus says why it closed.
				if (l.state === 'closed') close();
				say(l);
			});
			s.onmessage = (e) => {
				let m: ToShell;
				try {
					m = JSON.parse(e.data);
				} catch {
					return;
				}
				shell.forEach((cb) => cb(m));
			};
			// The browser reconnects a dropped stream itself; a refused one (a 4xx/5xx) stays closed.
			s.onerror = () => {
				if (es !== s) return;
				tab = null;
				const gone = s.readyState === EventSource.CLOSED;
				if (gone) close();
				say({
					state: 'closed',
					reason: gone ? 'the face refused the stream' : 'the stream dropped; reconnecting'
				});
			};
		},
		async send(msg) {
			if (!tab) throw new Error('not connected');
			const r = await fetch(`${base}/send`, {
				method: 'POST',
				headers: { 'content-type': 'application/json', 'x-iris-tab': tab },
				body: JSON.stringify(msg)
			});
			if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
		},
		async onShell(cb) {
			shell.add(cb);
			return () => shell.delete(cb);
		},
		async onLink(cb) {
			link.add(cb);
			return () => link.delete(cb);
		},
		async loadLayout() {
			const l = await usGet<Layout>(NS, 'layout');
			return l?.version === 2 && Array.isArray(l.workspaces) && l.workspaces.length ? l : empty();
		},
		saveLayout: (layout) => usSet(NS, 'layout', layout),
		async exportCsv(name, csv) {
			const a = document.createElement('a');
			a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
			a.download = `${name}.csv`;
			a.click();
			setTimeout(() => URL.revokeObjectURL(a.href), 1000);
			return `${name}.csv (your browser's downloads)`;
		},
		close
	};
}
