import { describe, it, expect } from 'vitest';
import { FACE_LAYOUTS, FACE_WALLPAPERS, FACE_CONTROLS } from './defaults';
import type { LayoutSpec, WallpaperSpec, ControlEntry } from '$lib/contracts';

const uniqueSlugs = (rows: { slug: string }[]) =>
	new Set(rows.map((r) => r.slug)).size === rows.length;

describe('face repo-default (SoC) config', () => {
	it('every built-in set is non-empty', () => {
		expect(FACE_LAYOUTS.length).toBeGreaterThan(0);
		expect(FACE_WALLPAPERS.length).toBeGreaterThan(0);
		expect(FACE_CONTROLS.length).toBeGreaterThan(0);
	});

	it('slugs are unique within each set', () => {
		expect(uniqueSlugs(FACE_LAYOUTS)).toBe(true);
		expect(uniqueSlugs(FACE_WALLPAPERS)).toBe(true);
		expect(uniqueSlugs(FACE_CONTROLS)).toBe(true);
	});

	it('every row is a repo-owned system row', () => {
		for (const row of [...FACE_LAYOUTS, ...FACE_WALLPAPERS, ...FACE_CONTROLS]) {
			expect(row.system).toBe(true);
		}
	});

	describe('layouts (LayoutSpec)', () => {
		it('ships the documented built-ins', () => {
			expect(FACE_LAYOUTS.map((l) => l.slug).sort()).toEqual(
				['2x2', 'half-h', 'half-v', 'single', 'thirds'].sort()
			);
		});

		it('validates against the LayoutSpec shape', () => {
			for (const l of FACE_LAYOUTS) {
				const spec: LayoutSpec = l;
				expect(typeof spec.slug).toBe('string');
				expect(spec.slug.length).toBeGreaterThan(0);
				expect(typeof spec.name).toBe('string');
				expect(typeof spec.icon).toBe('string');
				expect(typeof spec.system).toBe('boolean');
				expect(Array.isArray(spec.cells)).toBe(true);
				expect(spec.cells.length).toBeGreaterThan(0);
			}
		});

		it('cell fractions are in [0,1], stay inside the work area, and tile it', () => {
			for (const l of FACE_LAYOUTS) {
				const ids = new Set<string>();
				let covered = 0;
				for (const c of l.cells) {
					expect(ids.has(c.id)).toBe(false); // unique cell ids per layout
					ids.add(c.id);
					for (const v of [c.x, c.y, c.w, c.h]) {
						expect(v).toBeGreaterThanOrEqual(0);
						expect(v).toBeLessThanOrEqual(1);
					}
					expect(c.w).toBeGreaterThan(0);
					expect(c.h).toBeGreaterThan(0);
					// cell stays within the work area
					expect(c.x + c.w).toBeLessThanOrEqual(1 + 1e-9);
					expect(c.y + c.h).toBeLessThanOrEqual(1 + 1e-9);
					covered += c.w * c.h;
				}
				// the cells tile the full work area (no gap, no overlap surplus)
				expect(Math.abs(covered - 1)).toBeLessThan(1e-9);
			}
		});
	});

	describe('wallpapers (WallpaperSpec)', () => {
		it('seeds aurora/graphite/sunset/forest', () => {
			expect(FACE_WALLPAPERS.map((w) => w.slug).sort()).toEqual(
				['aurora', 'forest', 'graphite', 'sunset'].sort()
			);
		});

		it('validates against the WallpaperSpec shape', () => {
			for (const w of FACE_WALLPAPERS) {
				const spec: WallpaperSpec = w;
				expect(typeof spec.slug).toBe('string');
				expect(typeof spec.name).toBe('string');
				expect(['gradient', 'image']).toContain(spec.kind);
				expect(typeof spec.system).toBe('boolean');
				if (spec.kind === 'gradient') {
					expect(typeof spec.gradient).toBe('string');
					expect(spec.gradient!.length).toBeGreaterThan(0);
				} else {
					expect(typeof spec.vfsPath).toBe('string');
				}
			}
		});
	});

	describe('controls (ControlEntry)', () => {
		it('seeds Wallpaper/Layouts/Identity/Storage', () => {
			expect(FACE_CONTROLS.map((c) => c.slug).sort()).toEqual(
				['identity', 'layouts', 'storage', 'wallpaper'].sort()
			);
		});

		it('validates against the ControlEntry shape', () => {
			const surfaces = ['wallpaper', 'layouts', 'identity', 'storage', 'rawDataTable'];
			for (const c of FACE_CONTROLS) {
				const spec: ControlEntry = c;
				expect(typeof spec.slug).toBe('string');
				expect(typeof spec.name).toBe('string');
				expect(typeof spec.icon).toBe('string');
				expect(surfaces).toContain(spec.surface);
				expect(typeof spec.system).toBe('boolean');
				// rawDataTable surfaces must name their table; others must not need one
				if (spec.surface === 'rawDataTable') {
					expect(typeof spec.table).toBe('string');
				}
			}
		});
	});
});
