/**
 * Pure VFS path helpers — POSIX-ish, always RELATIVE to the user root (no
 * leading slash, `.`/`..` collapsed). Shared by the Files app and the
 * file-picker so navigation math lives in one tested place. Bone re-asserts
 * realpath-∈-scope server-side; these helpers are UX-only, never a security
 * boundary.
 */

/** Collapse `.`/`..`/empty segments into a clean relative path. */
export function normalizePath(p: string): string {
	const out: string[] = [];
	for (const seg of (p ?? '').split('/')) {
		if (seg === '' || seg === '.') continue;
		if (seg === '..') out.pop();
		else out.push(seg);
	}
	return out.join('/');
}

/** Join a base dir + a child name into a normalized relative path. */
export function joinPath(base: string, name: string): string {
	return normalizePath(`${base}/${name}`);
}

/** The parent directory of a path (`''` at the root). */
export function parentPath(p: string): string {
	const n = normalizePath(p);
	const i = n.lastIndexOf('/');
	return i < 0 ? '' : n.slice(0, i);
}

/** The final segment of a path (`''` at the root). */
export function basename(p: string): string {
	const n = normalizePath(p);
	const i = n.lastIndexOf('/');
	return i < 0 ? n : n.slice(i + 1);
}

export interface Crumb {
	name: string;
	path: string;
}

/** Breadcrumb trail from the root to `p`, inclusive. The root crumb carries the
 *  empty path and a caller-chosen label (default "home"). */
export function crumbs(p: string, rootLabel = 'home'): Crumb[] {
	const trail: Crumb[] = [{ name: rootLabel, path: '' }];
	let acc = '';
	for (const seg of normalizePath(p).split('/').filter(Boolean)) {
		acc = acc ? `${acc}/${seg}` : seg;
		trail.push({ name: seg, path: acc });
	}
	return trail;
}
