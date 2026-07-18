/**
 * WM v2 · layouts (Wave-1 G3).
 *
 * Loads the tiling layouts from the `face.layouts` config DataTable (KEAP SoT via
 * the BFF) and maps rows → `LayoutSpec[]`. If the table is empty (KEAP down / not
 * yet seeded by G2), we fall back to a built-in default set so snapping ALWAYS
 * works. Exposes the layout list + the active layout as Svelte stores.
 *
 * Row shape (defensive — G2 owns the real column spec): a row maps to a layout
 * via `slug|id`, `name`, `icon`, `system`, and a `cells` field that is either a
 * JSON array or an already-parsed array of `{id?,x,y,w,h}` in [0..1] fractions.
 */
import { derived, get, writable, type Readable } from 'svelte/store';
import type { DataTableRow, LayoutCellSpec, LayoutSpec } from '$lib/contracts';
import { loadTable } from '$lib/api/tables';
import { activeLayoutSlug } from '$lib/stores/desktop';

// ── Built-in fallback set (SoC defaults) ────────────────────────────────────────

/** The repo-default layouts. Cells are fractions of the work area; ids are stable
 *  so persisted `snappedCell` values survive across sessions. */
export const BUILTIN_LAYOUTS: LayoutSpec[] = [
	{
		slug: 'single',
		name: 'Single',
		icon: '▢',
		system: true,
		cells: [{ id: 'full', x: 0, y: 0, w: 1, h: 1 }]
	},
	{
		slug: 'half-v',
		name: 'Halves (vertical split)',
		icon: '▯▯',
		system: true,
		cells: [
			{ id: 'left', x: 0, y: 0, w: 0.5, h: 1 },
			{ id: 'right', x: 0.5, y: 0, w: 0.5, h: 1 }
		]
	},
	{
		slug: 'half-h',
		name: 'Halves (horizontal split)',
		icon: '⊟',
		system: true,
		cells: [
			{ id: 'top', x: 0, y: 0, w: 1, h: 0.5 },
			{ id: 'bottom', x: 0, y: 0.5, w: 1, h: 0.5 }
		]
	},
	{
		slug: 'thirds',
		name: 'Thirds',
		icon: '▮▮▮',
		system: true,
		cells: [
			{ id: 'left', x: 0, y: 0, w: 1 / 3, h: 1 },
			{ id: 'center', x: 1 / 3, y: 0, w: 1 / 3, h: 1 },
			{ id: 'right', x: 2 / 3, y: 0, w: 1 / 3, h: 1 }
		]
	},
	{
		slug: '2x2',
		name: 'Grid 2×2',
		icon: '田',
		system: true,
		cells: [
			{ id: 'tl', x: 0, y: 0, w: 0.5, h: 0.5 },
			{ id: 'tr', x: 0.5, y: 0, w: 0.5, h: 0.5 },
			{ id: 'bl', x: 0, y: 0.5, w: 0.5, h: 0.5 },
			{ id: 'br', x: 0.5, y: 0.5, w: 0.5, h: 0.5 }
		]
	}
];

// ── Row → LayoutSpec mapping ─────────────────────────────────────────────────────

function num(v: unknown): number | null {
	const n = typeof v === 'string' ? Number(v) : (v as number);
	return typeof n === 'number' && Number.isFinite(n) ? n : null;
}

/** Coerce a raw cell (object / partial) into a valid `LayoutCellSpec`, or null. */
function toCell(raw: unknown, index: number): LayoutCellSpec | null {
	if (!raw || typeof raw !== 'object') return null;
	const r = raw as Record<string, unknown>;
	const x = num(r.x);
	const y = num(r.y);
	const w = num(r.w);
	const h = num(r.h);
	if (x === null || y === null || w === null || h === null) return null;
	const id = typeof r.id === 'string' && r.id ? r.id : `c${index}`;
	return { id, x, y, w, h };
}

/** Parse a row's `cells` field: an array, or a JSON-encoded array string. */
function parseCells(raw: unknown): LayoutCellSpec[] {
	let arr: unknown = raw;
	if (typeof raw === 'string') {
		try {
			arr = JSON.parse(raw);
		} catch {
			return [];
		}
	}
	if (!Array.isArray(arr)) return [];
	return arr.map(toCell).filter((c): c is LayoutCellSpec => c !== null);
}

/** Map one DataTable row → LayoutSpec, or null if it has no usable cells. */
export function rowToLayout(row: DataTableRow): LayoutSpec | null {
	const slug =
		(typeof row.slug === 'string' && row.slug) ||
		(typeof row.id === 'string' && row.id) ||
		(typeof row.name === 'string' && row.name) ||
		'';
	if (!slug) return null;
	const cells = parseCells(row.cells);
	if (cells.length === 0) return null;
	return {
		slug,
		name: typeof row.name === 'string' && row.name ? row.name : slug,
		icon: typeof row.icon === 'string' ? row.icon : '▢',
		system: row.system === true || row.system === 'true',
		cells
	};
}

// ── Stores ───────────────────────────────────────────────────────────────────────

/** All available layouts (fallback set until `loadLayouts()` resolves). */
export const layouts = writable<LayoutSpec[]>(BUILTIN_LAYOUTS);

/** The active layout, derived from the store list + the desktop's active slug.
 *  Falls back to the first layout (never null once `layouts` is non-empty). */
export const activeLayout: Readable<LayoutSpec> = derived(
	[layouts, activeLayoutSlug],
	([$layouts, $slug]) => $layouts.find((l) => l.slug === $slug) ?? $layouts[0] ?? BUILTIN_LAYOUTS[0]
);

/** Look up a layout by slug in the current store (built-ins as a last resort). */
export function getLayout(slug: string): LayoutSpec | undefined {
	return get(layouts).find((l) => l.slug === slug) ?? BUILTIN_LAYOUTS.find((l) => l.slug === slug);
}

/**
 * Load layouts from `face.layouts`. Maps rows → LayoutSpec; if the table is empty
 * or the fetch fails, keeps the built-in fallback set. Returns the resolved list.
 */
export async function loadLayouts(): Promise<LayoutSpec[]> {
	let resolved: LayoutSpec[] = BUILTIN_LAYOUTS;
	try {
		const table = await loadTable('face.layouts');
		const mapped = (table.rows ?? []).map(rowToLayout).filter((l): l is LayoutSpec => l !== null);
		if (mapped.length > 0) resolved = mapped;
	} catch {
		// KEAP/BFF unreachable → keep the built-in fallback so snapping still works.
	}
	layouts.set(resolved);
	// Keep the desktop's active slug valid against whatever set we resolved.
	if (!resolved.some((l) => l.slug === get(activeLayoutSlug))) {
		activeLayoutSlug.set(resolved[0]?.slug ?? 'single');
	}
	return resolved;
}
