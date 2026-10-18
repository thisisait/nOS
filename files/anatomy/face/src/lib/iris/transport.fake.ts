// A Transport for tests: records what Iris sends, and plays the thalamus's side by hand.
// connect() answers `link connected`, as the pupil's bridge does once the socket is up.
import type { Transport } from './transport';
import type { Link, ToShell, ToThalamus } from './wire';
import { empty, type Layout } from './workspace';

export function fakeTransport(layout: Layout = empty()) {
	const shell = new Set<(m: ToShell) => void>();
	const link = new Set<(l: Link) => void>();
	const fake = {
		sent: [] as ToThalamus[],
		saved: [] as Layout[],
		connects: 0,
		shell: (m: ToShell) => shell.forEach((cb) => cb(m)),
		link: (l: Link) => link.forEach((cb) => cb(l)),
		transport: {
			async connect() {
				fake.connects++;
				fake.link({ state: 'connected', reason: null });
			},
			async send(msg) {
				fake.sent.push(msg);
			},
			async onShell(cb) {
				shell.add(cb);
				return () => shell.delete(cb);
			},
			async onLink(cb) {
				link.add(cb);
				return () => link.delete(cb);
			},
			loadLayout: async () => structuredClone(layout),
			async saveLayout(l) {
				fake.saved.push(l);
			},
			exportCsv: async (name) => `~/Downloads/${name}.csv`
		} satisfies Transport
	};
	return fake;
}
