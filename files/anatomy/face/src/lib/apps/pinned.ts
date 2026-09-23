/**
 * Dock pinning — which apps hold a bar slot, and where the rest go.
 *
 * The bar is a FIXED 15 slots at default scaling: 14 pinned apps + the trailing
 * expander that opens the full app list. Everything not pinned lands in that
 * overlay, sorted by title.
 *
 * The pinned list is DATA, not hardcode: `DEFAULT_PINNED` is the vendored SoC
 * fallback and `loadPinned()` overrides it from the `face-dock` config
 * DataTable — the same KEAP-SoT-plus-fallback path `$lib/wm/layouts.ts` uses
 * for `face-layouts`. The server-side twin (`$lib/server/defaults.ts`
 * `FACE_DOCK`, which the BFF serves when KEAP is down and the KEAP seeder is
 * authored from) must stay in the same order; `pinned.test.ts` pins that.
 */
import { writable } from 'svelte/store';
import { loadTable } from '$lib/api/tables';

/** Total bar slots at default scaling: 14 pinned + 1 expander. */
export const DOCK_SLOTS = 15;

/** Slots on a phone's bottom bar: 4 pinned + the Home key. Same `splitDock`,
 *  same pin order — the mobile shell does NOT keep a second list. Four is what
 *  fits at 390px with a 48px target and the safe-area gutter. */
export const MOBILE_DOCK_SLOTS = 5;

/** Repo-default pin order: the native face apps first, then the services the
 *  operator reaches for daily. Keys are dock keys: a native registry slug,
 *  `control-panel`, or a hub key — which is the Wing systems `id`, NOT the
 *  hub_card slug (`code_server`, not `code-server`; measured against wing.db).
 *  A key the catalog does not carry simply leaves its slot empty. */
export const DEFAULT_PINNED: readonly string[] = [
	'files',
	'tables',
	'anatomy',
	'planner',
	'keap-explore',
	'books',
	'control-panel',
	'authentik',
	'grafana',
	'code_server',
	'n8n',
	'wing',
	'nextcloud',
	'dolibarr'
];

/** The live pin order (the SoC defaults until `loadPinned()` resolves). */
export const pinnedSlugs = writable<readonly string[]>(DEFAULT_PINNED);

/** Minimum shape `splitDock` needs — `DockApp` satisfies it. */
export interface Pinnable {
	key: string;
	title: string;
}

/**
 * Split a catalog into the bar and the overlay.
 *
 * The bar takes pinned apps IN PIN ORDER, up to `slots - 1` (the last slot is
 * the expander). A pinned app the catalog does not carry leaves the bar one
 * short rather than pulling an arbitrary app forward — a dock that silently
 * re-pins itself is worse than a visible gap. Everything else goes to the
 * overlay, sorted by title.
 */
export function splitDock<T extends Pinnable>(
	apps: readonly T[],
	pinned: readonly string[] = DEFAULT_PINNED,
	slots: number = DOCK_SLOTS
): { bar: T[]; rest: T[] } {
	const max = Math.max(0, slots - 1);
	const left = new Map(apps.map((a) => [a.key, a]));
	const bar: T[] = [];
	for (const key of pinned) {
		if (bar.length >= max) break;
		const app = left.get(key);
		if (!app) continue;
		bar.push(app);
		left.delete(key);
	}
	const rest = [...left.values()].sort((a, b) => a.title.localeCompare(b.title));
	return { bar, rest };
}

/** Map `face-dock` rows → a pin order. Rows carry `slug` + numeric `order`. */
export function rowsToPinned(rows: readonly Record<string, unknown>[]): string[] {
	return rows
		.map((r) => ({
			slug: typeof r.slug === 'string' ? r.slug : typeof r.id === 'string' ? r.id : '',
			order: Number(r.order)
		}))
		.filter((r) => r.slug !== '')
		.sort(
			(a, b) => (Number.isFinite(a.order) ? a.order : 0) - (Number.isFinite(b.order) ? b.order : 0)
		)
		.map((r) => r.slug);
}

/**
 * Load the pin order from `face-dock`. Keeps the vendored defaults when the
 * table is empty or the BFF is unreachable, so the bar is never empty.
 */
export async function loadPinned(): Promise<readonly string[]> {
	let resolved: readonly string[] = DEFAULT_PINNED;
	try {
		const table = await loadTable('face-dock');
		const mapped = rowsToPinned((table.rows ?? []) as Record<string, unknown>[]);
		if (mapped.length > 0) resolved = mapped;
	} catch {
		// KEAP/BFF unreachable → keep the vendored order.
	}
	pinnedSlugs.set(resolved);
	return resolved;
}
