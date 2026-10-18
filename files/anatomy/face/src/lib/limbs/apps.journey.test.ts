// @vitest-environment happy-dom
// App limbs end to end: an Act goes through dispatch, the window comes forward, the app
// (mounted as the desktop mounts it, via NativeHost) consumes its request and shows it.
import { flushSync, mount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { windows, _reset } from '$lib/stores/desktop';
import { _resetRegistry, registerBuiltinNativeApps } from '$lib/apps/native/registry';
import NativeHost from '$lib/components/NativeHost.svelte';
import { dispatch } from './dispatch';

const table = (slug: string, title: string) => ({
	slug,
	title,
	columns: [{ key: 'title', label: 'Title', kind: 'text' }],
	rows: [{ id: `${slug}-1`, slug: `${slug}-1`, title: `${title} row` }],
	source: 'keap'
});

function bff(u: URL): unknown {
	const q = Object.fromEntries(u.searchParams);
	if (u.pathname === '/bff/config') return {};
	if (u.pathname === '/bff/tables' && q.op === 'list')
		return {
			tables: [
				{ slug: 'notes', title: 'Notes', rowCount: 1 },
				{ slug: 'roadmap', title: 'Roadmap', rowCount: 1 }
			]
		};
	if (u.pathname === '/bff/tables')
		return table(q.slug, q.slug === 'roadmap' ? 'Roadmap' : 'Notes');
	if (u.pathname === '/bff/vfs' && q.op === 'list')
		return q.path === 'documents/plans'
			? {
					entries: [
						{ name: 'q4.md', path: 'documents/plans/q4.md', kind: 'file', size: 9, mtime: 0 }
					]
				}
			: { entries: [] };
	if (u.pathname === '/bff/vfs' && q.op === 'read') return { content: 'ship limbs' };
	throw new Error(`unexpected ${u}`);
}

/** Wait for what the person would see (the lazy component import takes real ticks). */
const sees = (el: Element, sel: string, text: string) =>
	vi.waitFor(() => {
		flushSync();
		expect(el.querySelector(sel)?.textContent).toContain(text);
	});
const top = () => get(windows).reduce((a, b) => (b.z > a.z ? b : a)).app;
const act = (app: string, action: string, params: Record<string, unknown>) =>
	dispatch({ act: `a-${app}`, app, action, params });
/** Mount a window's body the way the desktop does. */
const host = (app: string) => {
	const el = document.createElement('div');
	el.dataset.app = app;
	document.body.append(el);
	mount(NativeHost, { target: el, props: { app } });
	return el;
};

beforeEach(() => {
	_reset();
	_resetRegistry();
	registerBuiltinNativeApps();
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: URL | string) => {
			const body = JSON.stringify(bff(new URL(String(input), location.origin)));
			return new Response(body, { status: 200 });
		})
	);
});

afterEach(() => {
	document.body.replaceChildren();
	vi.unstubAllGlobals();
});

describe('limbs · app limbs, Act to what the person sees', () => {
	it('tables.open_table then files.reveal: each window comes forward showing the ask', async () => {
		expect(await act('tables', 'open_table', { slug: 'roadmap' })).toMatchObject({ ok: true });
		expect(top()).toBe('tables');
		const tables = host('tables');
		await sees(tables, '.t.sel', 'Roadmap');
		await sees(tables, '.main', 'Roadmap row');

		expect(await act('files', 'reveal', { path: 'documents/plans/q4.md' })).toMatchObject({
			ok: true
		});
		expect(top()).toBe('files');
		const files = host('files');
		await sees(files, '.preview', 'ship limbs');

		// The app is already mounted: the request still lands, and its window comes back up.
		expect(await act('tables', 'open_table', { slug: 'notes' })).toMatchObject({ ok: true });
		expect(top()).toBe('tables');
		await sees(tables, '.t.sel', 'Notes');
	});

	it('a table or file that is not there answers ok:false and opens nothing', async () => {
		for (const r of [
			await act('tables', 'open_table', { slug: 'nope' }),
			await act('files', 'reveal', { path: 'documents/plans/missing.md' })
		])
			expect(r.ok).toBe(false);
		expect(get(windows)).toEqual([]);
	});
});
