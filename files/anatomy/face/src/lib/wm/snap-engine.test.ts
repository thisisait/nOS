import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { snapEngine, cellAt } from './snap-engine';
import { BUILTIN_LAYOUTS } from './layouts';
import {
	windows,
	openWindow,
	snapWindow,
	useSnapEngine,
	activeLayoutSlug,
	_reset
} from '$lib/stores/desktop';
import type { LayoutSpec } from '$lib/contracts';

const AREA = { w: 1000, h: 800 };
const byId = (slug: string): LayoutSpec => BUILTIN_LAYOUTS.find((l) => l.slug === slug)!;

describe('snapEngine.cells / rectFor', () => {
	it('half-v right cell of a 1000x800 area = {x:500,y:0,w:500,h:800}', () => {
		const r = snapEngine.rectFor(byId('half-v'), 'right', AREA);
		expect(r).toEqual({ x: 500, y: 0, w: 500, h: 800 });
	});

	it('half-v left cell = {x:0,y:0,w:500,h:800}', () => {
		expect(snapEngine.rectFor(byId('half-v'), 'left', AREA)).toEqual({
			x: 0,
			y: 0,
			w: 500,
			h: 800
		});
	});

	it('half-h bottom cell = {x:0,y:400,w:1000,h:400}', () => {
		expect(snapEngine.rectFor(byId('half-h'), 'bottom', AREA)).toEqual({
			x: 0,
			y: 400,
			w: 1000,
			h: 400
		});
	});

	it('single full cell spans the whole area', () => {
		expect(snapEngine.rectFor(byId('single'), 'full', AREA)).toEqual({
			x: 0,
			y: 0,
			w: 1000,
			h: 800
		});
	});

	it('2x2 br cell = {x:500,y:400,w:500,h:400}', () => {
		expect(snapEngine.rectFor(byId('2x2'), 'br', AREA)).toEqual({
			x: 500,
			y: 400,
			w: 500,
			h: 400
		});
	});

	it('thirds cells tile flush with no gaps or overlaps (sum of widths = area)', () => {
		const cs = snapEngine.cells(byId('thirds'), AREA);
		expect(cs).toHaveLength(3);
		// Flush tiling: each cell's right edge equals the next cell's left edge.
		expect(cs[0].x).toBe(0);
		expect(cs[0].x + cs[0].w).toBe(cs[1].x);
		expect(cs[1].x + cs[1].w).toBe(cs[2].x);
		expect(cs[2].x + cs[2].w).toBe(1000);
	});

	it('rectFor resolves every cell of every built-in layout to a valid rect', () => {
		for (const layout of BUILTIN_LAYOUTS) {
			for (const cell of layout.cells) {
				const r = snapEngine.rectFor(layout, cell.id, AREA);
				expect(r, `${layout.slug}/${cell.id}`).not.toBeNull();
				expect(r!.w).toBeGreaterThan(0);
				expect(r!.h).toBeGreaterThan(0);
				expect(r!.x).toBeGreaterThanOrEqual(0);
				expect(r!.y).toBeGreaterThanOrEqual(0);
			}
		}
	});

	it('rectFor returns null for an unknown cell id', () => {
		expect(snapEngine.rectFor(byId('half-v'), 'nope', AREA)).toBeNull();
	});
});

describe('cellAt (drop hit-test)', () => {
	const cells = snapEngine.cells(byId('2x2'), AREA);

	it('resolves a point in the top-left quadrant', () => {
		expect(cellAt(cells, { x: 10, y: 10 })).toBe('tl');
	});
	it('resolves a point in the bottom-right quadrant', () => {
		expect(cellAt(cells, { x: 900, y: 700 })).toBe('br');
	});
	it('returns null for a point outside every cell', () => {
		expect(cellAt(cells, { x: 5000, y: 5000 })).toBeNull();
	});
});

describe('snapEngine ↔ desktop store', () => {
	beforeEach(() => _reset());

	it('registering the engine + snapping sets the snapped rect and snappedCell', () => {
		useSnapEngine(snapEngine);
		activeLayoutSlug.set('half-v');
		const id = openWindow({ app: 'files', title: 'Files' });
		snapWindow(id, byId('half-v'), 'right', AREA);
		const w = get(windows)[0];
		expect(w.snappedCell).toBe('right');
		expect(w.x).toBe(500);
		expect(w.y).toBe(0);
		expect(w.w).toBe(500);
		expect(w.h).toBe(800);
	});
});
