/**
 * Files-app logic that is not a component: sorting, name collisions, the
 * accounting-queue destination. Pure — no fetch, no DOM — so it is testable in
 * node (`files-ops.test.ts`) while the Svelte shell stays a thin view.
 *
 * Path MATH lives in `./paths.ts`; this file is about what the explorer DOES
 * with a listing. Neither is a security boundary — Bone re-asserts
 * realpath-∈-scope on every call (`files/anatomy/bone/vfs.py::_resolve`).
 */
import type { VfsEntry } from '$lib/api/vfs';

export type SortKey = 'name' | 'size' | 'mtime';

/** Sort a listing. Directories ALWAYS come first — on a touch target list, a
 *  folder that sorts between two files by size is a navigation trap. */
export function sortEntries(entries: VfsEntry[], key: SortKey = 'name'): VfsEntry[] {
	const cmp = (a: VfsEntry, b: VfsEntry) => {
		if (a.kind !== b.kind) return a.kind === 'dir' ? -1 : 1;
		if (key === 'size') return b.size - a.size || a.name.localeCompare(b.name);
		if (key === 'mtime') return b.mtime - a.mtime || a.name.localeCompare(b.name);
		return a.name.localeCompare(b.name);
	};
	return [...entries].sort(cmp);
}

/** `name` if free, else `name-2`, `name-3`, … keeping the extension. Used for
 *  camera shots, where every phone hands us the same `image.jpg`. */
export function uniqueName(name: string, taken: Iterable<string>): string {
	const used = new Set(taken);
	if (!used.has(name)) return name;
	const dot = name.lastIndexOf('.');
	const stem = dot > 0 ? name.slice(0, dot) : name;
	const ext = dot > 0 ? name.slice(dot) : '';
	for (let n = 2; n < 1000; n++) {
		const candidate = `${stem}-${n}${ext}`;
		if (!used.has(candidate)) return candidate;
	}
	return `${stem}-${Date.now()}${ext}`;
}

/** A dated filename for a camera capture: `photo-20260923-143005.jpg`.
 *  A phone hands over `image.jpg` (or nothing at all), which tells the operator
 *  nothing and collides on the second shot. */
export function cameraName(now: Date, original = ''): string {
	const dot = original.lastIndexOf('.');
	const ext = dot > 0 ? original.slice(dot).toLowerCase() : '.jpg';
	const p = (n: number) => String(n).padStart(2, '0');
	const stamp =
		`${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}` +
		`-${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}`;
	return `photo-${stamp}${ext}`;
}

/** The accounting intake parent. `files/anatomy/bone/vfs.py::_SKELETON` mints
 *  it for every user; the per-client leaf under it is a client-onboarding act,
 *  so the explorer never invents one. */
export const ACCOUNTING_ROOT = 'inbox/accounting';

/** Where "send to the backoffice queue" actually puts a document: the dir
 *  `tools/invoice-vision-intake.py::discover_intakes` globs
 *  (`inbox/accounting/<client>/incoming`). Moving the file there IS the hand-off —
 *  there is no second API to call. */
export function queueDest(client: string, name: string): string {
	return `${ACCOUNTING_ROOT}/${client}/incoming/${name}`;
}

/** Human size. `0 B` for an empty file, never for a directory (callers omit). */
export function formatSize(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	const units = ['kB', 'MB', 'GB', 'TB'];
	let n = bytes / 1024;
	let i = 0;
	while (n >= 1024 && i < units.length - 1) {
		n /= 1024;
		i++;
	}
	return `${n < 10 ? n.toFixed(1) : Math.round(n)} ${units[i]}`;
}
