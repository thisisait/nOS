/**
 * Active-wallpaper store (G4).
 *
 * Holds the desktop's active wallpaper and persists the *selection* (not the
 * catalog) to user-state ns `face.desktop` key `wallpaper`. The catalog itself
 * lives in the `face.wallpapers` DataTable (repo seed + user rows); this module
 * only tracks which one is active.
 *
 * Security: gradient specs are treated as untrusted (a user may add rows). We
 * NEVER inject raw strings — `safeBackground()` validates a gradient is a plain
 * CSS gradient (rejects `;`, `}`, `url(`, comments) before it can reach a
 * `style` binding, and image wallpapers only resolve to a BFF-proxied VFS path.
 */
import { writable, get } from 'svelte/store';
import { usGet, usSet } from '$lib/api/userstate';
import type { WallpaperSpec, DataTable } from '$lib/contracts';

/** user-state home for desktop prefs. */
export const DESKTOP_NS = 'face.desktop';
export const WALLPAPER_KEY = 'wallpaper';

/** Repo-seeded fallbacks (used when `face.wallpapers` is empty / KEAP down). */
export const FALLBACK_WALLPAPERS: WallpaperSpec[] = [
	{
		slug: 'aurora',
		name: 'Aurora',
		kind: 'gradient',
		gradient: 'radial-gradient(1200px 800px at 30% 20%, #16203a, #0b0d12 60%)',
		system: true
	},
	{
		slug: 'graphite',
		name: 'Graphite',
		kind: 'gradient',
		gradient: 'linear-gradient(160deg, #2a2d34, #0e1013)',
		system: true
	},
	{
		slug: 'sunset',
		name: 'Sunset',
		kind: 'gradient',
		gradient: 'linear-gradient(160deg, #3a1c2e, #7a3b2e 60%, #12080a)',
		system: true
	},
	{
		slug: 'forest',
		name: 'Forest',
		kind: 'gradient',
		gradient: 'linear-gradient(160deg, #16281c, #0b1a12 60%, #050a07)',
		system: true
	}
];

/** The active wallpaper (defaults to the first fallback). */
export const activeWallpaper = writable<WallpaperSpec>(FALLBACK_WALLPAPERS[0]);

/**
 * Project a `face.wallpapers` DataTable into typed specs, keeping only rows that
 * pass validation. Falls back to the repo built-ins when the table is empty /
 * unreachable so the picker always has something to show.
 */
export function wallpapersFromTable(table: DataTable | null): WallpaperSpec[] {
	const rows = table?.rows ?? [];
	const specs: WallpaperSpec[] = [];
	for (const r of rows) {
		const kind = r.kind === 'image' ? 'image' : 'gradient';
		const spec: WallpaperSpec = {
			slug: String(r.slug ?? r.id ?? ''),
			name: String(r.name ?? r.slug ?? r.id ?? 'Untitled'),
			kind,
			gradient: typeof r.gradient === 'string' ? r.gradient : undefined,
			vfsPath: typeof r.vfsPath === 'string' ? r.vfsPath : undefined,
			system: r.system === true || r.system === 'true'
		};
		if (spec.slug && safeBackground(spec) !== null) specs.push(spec);
	}
	return specs.length > 0 ? specs : FALLBACK_WALLPAPERS;
}

/**
 * Validate a gradient string is a *plain* CSS gradient and safe to drop into a
 * `background` style. Rejects anything that could break out of the value:
 * statement terminators, rule/block braces, comments, and any `url(...)`.
 */
export function isSafeGradient(spec: string | undefined): spec is string {
	if (typeof spec !== 'string') return false;
	const s = spec.trim();
	if (s.length === 0 || s.length > 512) return false;
	if (/[;{}]/.test(s)) return false;
	if (s.includes('/*') || s.includes('*/')) return false;
	if (/url\s*\(/i.test(s)) return false;
	if (/expression\s*\(/i.test(s)) return false;
	// Must actually be a gradient function, not arbitrary CSS.
	if (!/^(repeating-)?(linear|radial|conic)-gradient\s*\(.*\)$/i.test(s)) return false;
	return true;
}

/** Approved VFS image path shape: under the user's tree, streamed by the BFF. */
export function isSafeVfsPath(p: string | undefined): p is string {
	if (typeof p !== 'string') return false;
	const s = p.trim();
	if (s.length === 0 || s.length > 512) return false;
	if (s.includes('..')) return false;
	if (/[;{}'"()]/.test(s)) return false;
	// Relative path under the user's tree; the BFF /bff/vfs endpoint enforces the
	// uid partition — we only gate the string shape here.
	return /^[A-Za-z0-9._/-]+$/.test(s);
}

/**
 * Resolve a wallpaper spec to a CSS `background` value, or null if it fails
 * validation (caller keeps the previous background). Never throws, never emits
 * an unvalidated string.
 */
export function safeBackground(spec: WallpaperSpec | null | undefined): string | null {
	if (!spec) return null;
	if (spec.kind === 'gradient') {
		return isSafeGradient(spec.gradient) ? spec.gradient : null;
	}
	if (spec.kind === 'image') {
		if (!isSafeVfsPath(spec.vfsPath)) return null;
		// Stream the image through the BFF's download op (G5): a bare path returns
		// a JSON dir listing, not the bytes.
		const url = `/bff/vfs?op=download&path=${encodeURIComponent(spec.vfsPath)}`;
		return `center / cover no-repeat url("${url}")`;
	}
	return null;
}

/** Set + persist the active wallpaper. Rejects specs that fail validation. */
export async function setWallpaper(spec: WallpaperSpec): Promise<void> {
	if (safeBackground(spec) === null) return;
	activeWallpaper.set(spec);
	try {
		await usSet(DESKTOP_NS, WALLPAPER_KEY, spec);
	} catch {
		// Persist is best-effort; the in-memory selection still applies this session.
	}
}

/** Load the saved wallpaper (if any) into the store. Call once on desktop mount.
 *  Returns the resolved active wallpaper. */
export async function initWallpaper(): Promise<WallpaperSpec> {
	try {
		const saved = await usGet<WallpaperSpec>(DESKTOP_NS, WALLPAPER_KEY);
		if (saved && safeBackground(saved) !== null) {
			activeWallpaper.set(saved);
		}
	} catch {
		// keep the default fallback
	}
	return get(activeWallpaper);
}
