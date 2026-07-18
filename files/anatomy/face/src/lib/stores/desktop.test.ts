import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import {
	windows,
	openWindow,
	closeWindow,
	focusWindow,
	moveWindow,
	snapWindow,
	useSnapEngine,
	usePersistence,
	restoreGeometry,
	_reset,
	type SnapEngine,
	type PersistenceAdapter
} from './desktop';
import type { LayoutSpec, WindowGeometry, WindowModel } from '$lib/contracts';

const LAYOUT: LayoutSpec = {
	slug: 'half-v',
	name: 'Halves',
	icon: 'split',
	system: true,
	cells: [
		{ id: 'l', x: 0, y: 0, w: 0.5, h: 1 },
		{ id: 'r', x: 0.5, y: 0, w: 0.5, h: 1 }
	]
};

const engine: SnapEngine = {
	cells: (layout, area) =>
		layout.cells.map((c) => ({
			id: c.id,
			x: c.x * area.w,
			y: c.y * area.h,
			w: c.w * area.w,
			h: c.h * area.h
		})),
	rectFor: (layout, cellId, area) => {
		const c = layout.cells.find((x) => x.id === cellId);
		return c ? { x: c.x * area.w, y: c.y * area.h, w: c.w * area.w, h: c.h * area.h } : null;
	}
};

beforeEach(() => _reset());

describe('desktop store', () => {
	it('opens, focuses (raises z), and closes windows', () => {
		const a = openWindow({ app: 'files', title: 'Files' });
		const b = openWindow({ app: 'notes', title: 'Notes' });
		let list = get(windows);
		expect(list).toHaveLength(2);
		const zA = list.find((w) => w.id === a)!.z;
		focusWindow(a);
		list = get(windows);
		expect(list.find((w) => w.id === a)!.z).toBeGreaterThan(zA);
		expect(list.find((w) => w.id === a)!.z).toBeGreaterThan(list.find((w) => w.id === b)!.z);
		closeWindow(a);
		expect(get(windows)).toHaveLength(1);
	});

	it('moving clears the snapped cell', () => {
		const id = openWindow({ app: 'files', title: 'Files', snappedCell: 'l' });
		moveWindow(id, 10, 10);
		expect(get(windows)[0].snappedCell).toBeUndefined();
	});

	it('snaps a window into a layout cell via the registered SnapEngine', () => {
		useSnapEngine(engine);
		const id = openWindow({ app: 'files', title: 'Files' });
		snapWindow(id, LAYOUT, 'r', { w: 1000, h: 800 });
		const w = get(windows)[0];
		expect(w.snappedCell).toBe('r');
		expect(w.x).toBe(500);
		expect(w.w).toBe(500);
	});

	it('notifies the persistence adapter on geometry change and restores', async () => {
		let seen: WindowModel[] = [];
		const saved: WindowGeometry[] = [];
		const adapter: PersistenceAdapter = {
			onChange: (ws) => {
				seen = ws;
			},
			restore: async () => saved
		};
		usePersistence(adapter);
		const id = openWindow({ app: 'files', title: 'Files' });
		moveWindow(id, 123, 45);
		expect(seen.find((w) => w.id === id)?.x).toBe(123);

		saved.push({ id, app: 'files', x: 300, y: 200, w: 400, h: 300, z: 5, min: false });
		await restoreGeometry();
		const w = get(windows)[0];
		expect(w.x).toBe(300);
		expect(w.y).toBe(200);
	});
});
