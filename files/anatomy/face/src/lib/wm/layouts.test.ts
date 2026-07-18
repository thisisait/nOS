import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import {
	BUILTIN_LAYOUTS,
	rowToLayout,
	loadLayouts,
	layouts,
	activeLayout,
	getLayout
} from './layouts';
import { activeLayoutSlug } from '$lib/stores/desktop';

describe('BUILTIN_LAYOUTS', () => {
	it('ships the five documented fallback layouts', () => {
		const slugs = BUILTIN_LAYOUTS.map((l) => l.slug).sort();
		expect(slugs).toEqual(['2x2', 'half-h', 'half-v', 'single', 'thirds']);
	});

	it('every built-in cell uses fractions within [0..1]', () => {
		for (const l of BUILTIN_LAYOUTS) {
			for (const c of l.cells) {
				for (const v of [c.x, c.y, c.w, c.h]) {
					expect(v).toBeGreaterThanOrEqual(0);
					expect(v).toBeLessThanOrEqual(1);
				}
			}
		}
	});
});

describe('rowToLayout', () => {
	it('maps a row with a parsed cells array', () => {
		const spec = rowToLayout({
			id: 'r1',
			slug: 'my-split',
			name: 'My Split',
			icon: '▯▯',
			system: false,
			cells: [
				{ id: 'a', x: 0, y: 0, w: 0.5, h: 1 },
				{ id: 'b', x: 0.5, y: 0, w: 0.5, h: 1 }
			]
		});
		expect(spec).not.toBeNull();
		expect(spec!.slug).toBe('my-split');
		expect(spec!.system).toBe(false);
		expect(spec!.cells).toHaveLength(2);
	});

	it('parses a JSON-string cells field (rawDataTable json column)', () => {
		const spec = rowToLayout({
			id: 'r2',
			name: 'Encoded',
			cells: '[{"x":0,"y":0,"w":1,"h":1}]'
		});
		expect(spec).not.toBeNull();
		expect(spec!.slug).toBe('r2'); // slug|id|name precedence → id wins
		expect(spec!.name).toBe('Encoded');
		expect(spec!.cells[0].id).toBe('c0'); // synthesised id
	});

	it('coerces string "system" and string numbers', () => {
		const spec = rowToLayout({
			id: 'r3',
			slug: 's',
			system: 'true',
			cells: '[{"x":"0","y":"0","w":"0.5","h":"1"}]'
		});
		expect(spec!.system).toBe(true);
		expect(spec!.cells[0].w).toBe(0.5);
	});

	it('returns null for a row with no usable cells', () => {
		expect(rowToLayout({ id: 'x', slug: 'x', cells: 'not-json' })).toBeNull();
		expect(rowToLayout({ id: 'y', slug: 'y', cells: [] })).toBeNull();
		expect(rowToLayout({ id: 'z', cells: [{ x: 0, y: 0, w: 1, h: 1 }] } as never)).not.toBeNull();
	});
});

describe('loadLayouts (fallback path)', () => {
	beforeEach(() => {
		layouts.set(BUILTIN_LAYOUTS);
		activeLayoutSlug.set('single');
	});

	it('keeps the built-in set when the table fetch fails (no network in node)', async () => {
		const resolved = await loadLayouts();
		// loadTable → fetch is unavailable in the node test env → caught → fallback.
		expect(resolved).toEqual(BUILTIN_LAYOUTS);
		expect(get(layouts)).toEqual(BUILTIN_LAYOUTS);
	});

	it('activeLayout derives from the desktop active slug', () => {
		activeLayoutSlug.set('2x2');
		expect(get(activeLayout).slug).toBe('2x2');
		activeLayoutSlug.set('does-not-exist');
		// Falls back to the first available layout rather than null.
		expect(get(activeLayout)).toBeTruthy();
	});

	it('getLayout finds a built-in by slug', () => {
		expect(getLayout('thirds')!.cells).toHaveLength(3);
		expect(getLayout('nope')).toBeUndefined();
	});
});
