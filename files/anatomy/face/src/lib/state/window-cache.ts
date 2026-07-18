/**
 * Per-viewport window-position cache (G4).
 *
 * Implements the desktop store's `PersistenceAdapter` seam: on every geometry
 * mutation the store calls `onChange`; we coalesce those into a single DEBOUNCED
 * (30 s) write to user-state ns `face.windows`, keyed by the current viewport
 * bucket. `restore()` reads the bucket for the current viewport (returns null →
 * the store cascades fresh windows for an unseen viewport).
 *
 * Bucketing: we round innerWidth/innerHeight to the nearest 100 px and key as
 * "<w>x<h>" (e.g. 1440x900 → "1400x900"). Rounding absorbs the ±1 px chrome
 * jitter (scrollbars, zoom, devtools) that would otherwise fragment one physical
 * display across many near-identical buckets, while still giving a laptop vs an
 * external 4K their own remembered layouts.
 */
import { usGet, usSet } from '$lib/api/userstate';
import { usePersistence, restoreGeometry } from '$lib/stores/desktop';
import type { PersistenceAdapter } from '$lib/stores/desktop';
import type { WindowModel, WindowGeometry } from '$lib/contracts';

/** user-state namespace for cached window geometry. */
export const WINDOWS_NS = 'face.windows';
/** Debounce window for coalesced writes. */
export const DEBOUNCE_MS = 30_000;

/** Round to the nearest 100 px (floor 100) so near-identical viewports collapse
 *  onto one bucket. */
function round100(n: number): number {
	return Math.max(100, Math.round(n / 100) * 100);
}

/** The user-state key for a viewport: "<w>x<h>" bucketed to nearest 100. */
export function viewportBucket(w: number, h: number): string {
	return `${round100(w)}x${round100(h)}`;
}

/** Serialize live windows to the persisted subset (drops title/max — a maximized
 *  window restores to its underlying rect). */
export function toGeometry(list: WindowModel[]): WindowGeometry[] {
	return list.map((w) => ({
		id: w.id,
		app: w.app,
		x: w.x,
		y: w.y,
		w: w.w,
		h: w.h,
		z: w.z,
		min: w.min,
		...(w.snappedCell !== undefined ? { snappedCell: w.snappedCell } : {})
	}));
}

/** A viewport reader — overridable for tests / SSR. */
export type ViewportFn = () => { w: number; h: number };

const browserViewport: ViewportFn = () =>
	typeof window !== 'undefined'
		? { w: window.innerWidth, h: window.innerHeight }
		: { w: 1280, h: 800 };

export interface WindowCacheOptions {
	/** How to read the current viewport (defaults to `window.inner*`). */
	getViewport?: ViewportFn;
	/** Debounce window in ms (defaults to 30 s). */
	debounceMs?: number;
}

/**
 * Build the persistence adapter. Writes are debounced + coalesced: only the last
 * geometry seen inside a `debounceMs` window is flushed, and it lands in the
 * bucket for the viewport at flush time.
 */
export function createWindowCache(opts: WindowCacheOptions = {}): PersistenceAdapter {
	const getViewport = opts.getViewport ?? browserViewport;
	const debounceMs = opts.debounceMs ?? DEBOUNCE_MS;

	let pending: WindowGeometry[] | null = null;
	let timer: ReturnType<typeof setTimeout> | null = null;

	async function flush(): Promise<void> {
		timer = null;
		if (pending === null) return;
		const geo = pending;
		pending = null;
		const { w, h } = getViewport();
		try {
			await usSet(WINDOWS_NS, viewportBucket(w, h), geo);
		} catch {
			// A dropped write is non-fatal; the next mutation re-arms and retries.
		}
	}

	return {
		onChange(list: WindowModel[]): void {
			pending = toGeometry(list);
			if (timer === null) {
				timer = setTimeout(() => void flush(), debounceMs);
			}
		},
		async restore(): Promise<WindowGeometry[] | null> {
			const { w, h } = getViewport();
			try {
				return await usGet<WindowGeometry[]>(WINDOWS_NS, viewportBucket(w, h));
			} catch {
				return null;
			}
		}
	};
}

/**
 * Wire the cache into the desktop store and restore the current viewport's
 * layout. The integrator calls this once on desktop mount (after windows the
 * shell auto-opens have been created, so their ids can be matched).
 */
export async function initWindowCache(opts: WindowCacheOptions = {}): Promise<void> {
	usePersistence(createWindowCache(opts));
	await restoreGeometry();
}
