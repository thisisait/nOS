// The Tauri transport says exactly what App.svelte said to the bridge before the seam:
// the same commands with the same arguments (bridge.rs, workspace.rs, export.rs), the same two events.
import { afterEach, describe, expect, it } from 'vitest';
import { tauriTransport } from './transport.tauri';

const calls: [string, unknown][] = [];
const heard: string[] = [];
const fake = {
	core: { invoke: async (cmd: string, args?: unknown) => (calls.push([cmd, args]), cmd === 'export_csv' ? '/Downloads/a.csv' : 'ok') },
	event: {
		listen: async (ev: string, cb: (e: { payload: unknown }) => void) => {
			heard.push(ev);
			cb({ payload: ev });
			return () => {};
		}
	}
};
const g = globalThis as { __TAURI__?: unknown };

afterEach(() => {
	delete g.__TAURI__;
	calls.length = heard.length = 0;
});

describe('the Tauri transport', () => {
	it('is absent outside the pupil app', () => {
		expect(tauriTransport()).toBeNull();
	});

	it('maps every call onto the bridge command App used', async () => {
		g.__TAURI__ = fake;
		const t = tauriTransport()!;
		const layout = { v: 1 } as never;
		await t.connect();
		await t.send({ t: 'resume' });
		await t.loadLayout();
		await t.saveLayout(layout);
		expect(await t.exportCsv('rows', 'a,b')).toBe('/Downloads/a.csv');
		expect(calls).toEqual([
			['connect', undefined],
			['send', { msg: { t: 'resume' } }],
			['load_layout', undefined],
			['save_layout', { layout }],
			['export_csv', { name: 'rows', csv: 'a,b' }]
		]);
	});

	it('hands each listener the payload of to_shell and link', async () => {
		g.__TAURI__ = fake;
		const t = tauriTransport()!;
		const got: unknown[] = [];
		await t.onShell((m) => got.push(m));
		await t.onLink((l) => got.push(l));
		expect(heard).toEqual(['to_shell', 'link']);
		expect(got).toEqual(['to_shell', 'link']);
	});
});
