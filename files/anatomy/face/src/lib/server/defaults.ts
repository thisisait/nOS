/**
 * nOS-face repo-default (SoC) config — the built-in `system` rows.
 *
 * Layer 1 of the SoC → runtime DataTable → per-user-state pattern
 * (docs/plans/nos-face-shell-v2.md): these are the version-controlled defaults
 * the KEAP config DataTables (face.layouts / face.wallpapers / face.controls)
 * are seeded from (roles/pazny.keap/tasks/seed-face-tables.yml), AND the
 * fallback the BFF serves when KEAP is unconfigured/unreachable so the desktop
 * stays usable. Every row carries `system: true` — users add their own rows on
 * top; only these are repo-owned.
 *
 * Types are the frozen shell contracts (src/lib/contracts) — keep this the
 * source of truth for the built-ins and mirror any change into the KEAP seeder.
 */
import type { LayoutSpec, WallpaperSpec, ControlEntry } from '$lib/contracts';

const THIRD = 1 / 3;

/** Built-in tiling layouts. Cells are fractions of the work area, each in [0,1];
 *  every set tiles the full area (Σ w·h ≈ 1). */
export const FACE_LAYOUTS: LayoutSpec[] = [
	{
		slug: 'single',
		name: 'Single',
		icon: 'square',
		system: true,
		cells: [{ id: 'full', x: 0, y: 0, w: 1, h: 1 }]
	},
	{
		slug: 'half-v',
		name: 'Halves',
		icon: 'columns-2',
		system: true,
		cells: [
			{ id: 'left', x: 0, y: 0, w: 0.5, h: 1 },
			{ id: 'right', x: 0.5, y: 0, w: 0.5, h: 1 }
		]
	},
	{
		slug: 'half-h',
		name: 'Stack',
		icon: 'rows-2',
		system: true,
		cells: [
			{ id: 'top', x: 0, y: 0, w: 1, h: 0.5 },
			{ id: 'bottom', x: 0, y: 0.5, w: 1, h: 0.5 }
		]
	},
	{
		slug: 'thirds',
		name: 'Thirds',
		icon: 'columns-3',
		system: true,
		cells: [
			{ id: 'left', x: 0, y: 0, w: THIRD, h: 1 },
			{ id: 'center', x: THIRD, y: 0, w: THIRD, h: 1 },
			{ id: 'right', x: 2 * THIRD, y: 0, w: THIRD, h: 1 }
		]
	},
	{
		slug: '2x2',
		name: 'Grid',
		icon: 'grid-2x2',
		system: true,
		cells: [
			{ id: 'tl', x: 0, y: 0, w: 0.5, h: 0.5 },
			{ id: 'tr', x: 0.5, y: 0, w: 0.5, h: 0.5 },
			{ id: 'bl', x: 0, y: 0.5, w: 0.5, h: 0.5 },
			{ id: 'br', x: 0.5, y: 0.5, w: 0.5, h: 0.5 }
		]
	}
];

/** Built-in wallpapers — CSS gradient specs. Users add gradients or VFS images. */
export const FACE_WALLPAPERS: WallpaperSpec[] = [
	{
		slug: 'aurora',
		name: 'Aurora',
		kind: 'gradient',
		gradient: 'linear-gradient(135deg, #1e3a8a 0%, #0f766e 50%, #4c1d95 100%)',
		system: true
	},
	{
		slug: 'graphite',
		name: 'Graphite',
		kind: 'gradient',
		gradient: 'linear-gradient(135deg, #1f2937 0%, #374151 50%, #111827 100%)',
		system: true
	},
	{
		slug: 'sunset',
		name: 'Sunset',
		kind: 'gradient',
		gradient: 'linear-gradient(135deg, #7c2d12 0%, #b45309 45%, #be185d 100%)',
		system: true
	},
	{
		slug: 'forest',
		name: 'Forest',
		kind: 'gradient',
		gradient: 'linear-gradient(135deg, #14532d 0%, #166534 50%, #052e16 100%)',
		system: true
	}
];

/** Built-in control-panel surfaces. Clicking a row opens a window hosting the
 *  surface (a rawDataTable initially, a bespoke editor later). */
export const FACE_CONTROLS: ControlEntry[] = [
	{ slug: 'wallpaper', name: 'Wallpaper', icon: 'image', surface: 'wallpaper', system: true },
	{ slug: 'layouts', name: 'Layouts', icon: 'layout-dashboard', surface: 'layouts', system: true },
	{ slug: 'identity', name: 'Identity', icon: 'user', surface: 'identity', system: true },
	{ slug: 'storage', name: 'Storage', icon: 'hard-drive', surface: 'storage', system: true }
];
