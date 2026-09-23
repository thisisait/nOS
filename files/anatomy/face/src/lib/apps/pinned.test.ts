import { describe, it, expect } from 'vitest';
import { DEFAULT_PINNED, DOCK_SLOTS, MOBILE_DOCK_SLOTS, splitDock, rowsToPinned } from './pinned';
import { FACE_DOCK } from '$lib/server/defaults';

const app = (key: string, title = key) => ({ key, title });
/** A catalog holding every pinned app plus three that are not pinned. */
const catalog = [...DEFAULT_PINNED.map((k) => app(k)), app('zulip'), app('kiwix'), app('adam')];

describe('dock slots', () => {
	it('fills 14 pinned tiles + the expander = 15 slots', () => {
		const { bar } = splitDock(catalog);
		expect(DEFAULT_PINNED).toHaveLength(DOCK_SLOTS - 1);
		expect(bar).toHaveLength(DOCK_SLOTS - 1);
		expect(bar.length + 1).toBe(DOCK_SLOTS); // + the expander
		expect(bar.map((a) => a.key)).toEqual([...DEFAULT_PINNED]);
	});

	it('unpinned apps land in the overlay list, sorted by title', () => {
		const { bar, rest } = splitDock(catalog);
		expect(rest.map((a) => a.key)).toEqual(['adam', 'kiwix', 'zulip']);
		for (const a of rest) expect(bar).not.toContain(a);
		expect(bar.length + rest.length).toBe(catalog.length);
	});

	it('a missing pinned app leaves a gap rather than promoting another app', () => {
		const { bar, rest } = splitDock([app('files'), app('zulip')]);
		expect(bar.map((a) => a.key)).toEqual(['files']);
		expect(rest.map((a) => a.key)).toEqual(['zulip']);
	});

	it('the phone bar is the SAME pin order, four deep — not a second list', () => {
		const { bar } = splitDock(catalog, DEFAULT_PINNED, MOBILE_DOCK_SLOTS);
		expect(bar.map((a) => a.key)).toEqual([...DEFAULT_PINNED].slice(0, MOBILE_DOCK_SLOTS - 1));
	});

	it('extra pins beyond the bar overflow into the overlay', () => {
		const pins = [...DEFAULT_PINNED, 'zulip'];
		const { bar, rest } = splitDock(catalog, pins);
		expect(bar).toHaveLength(DOCK_SLOTS - 1);
		expect(rest.map((a) => a.key)).toContain('zulip');
	});
});

describe('face-dock rows', () => {
	it('orders by the `order` column and drops rows with no slug', () => {
		expect(rowsToPinned([{ slug: 'b', order: 2 }, { slug: 'a', order: 1 }, { order: 3 }])).toEqual([
			'a',
			'b'
		]);
	});

	it('the vendored client order matches the server-side seed order', () => {
		expect(FACE_DOCK.map((r) => r.slug)).toEqual([...DEFAULT_PINNED]);
	});
});
