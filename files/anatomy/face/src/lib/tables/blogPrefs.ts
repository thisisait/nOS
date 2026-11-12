/**
 * Blog settings, viewer-local (row face-style-blog-settings): which columns a post shows as chips and
 * how many body lines come before the ellipsis. Per table, in this browser only; written to the KEAP
 * view block only after a ruling. Stored text is untrusted: a key that names no column, a line count
 * out of range or unparseable JSON is dropped, never guessed. Storage that throws (private window,
 * blocked site data) reads as "no settings" and a save that throws is a no-op.
 */
export type BlogPrefs = { meta: string[]; lines: number }; // lines 0 = the whole body
export const MAX_LINES = 20;

const storeKey = (slug: string) => `nos-face:blog:${slug}`;

export function parseBlogPrefs(
	raw: string | null,
	columns: readonly { key: string }[]
): BlogPrefs | null {
	if (!raw) return null;
	let v: unknown;
	try {
		v = JSON.parse(raw);
	} catch {
		return null;
	}
	if (!v || typeof v !== 'object' || Array.isArray(v)) return null;
	const o = v as Record<string, unknown>;
	const known = new Set(columns.map((c) => c.key));
	const meta = Array.isArray(o.meta)
		? [...new Set(o.meta.filter((k): k is string => typeof k === 'string' && known.has(k)))]
		: [];
	const n = o.lines;
	const lines = typeof n === 'number' && Number.isInteger(n) && n >= 0 && n <= MAX_LINES ? n : 0;
	return { meta, lines };
}

export function loadBlogPrefs(slug: string, columns: readonly { key: string }[]): BlogPrefs | null {
	try {
		return parseBlogPrefs(localStorage.getItem(storeKey(slug)), columns);
	} catch {
		return null;
	}
}

export function saveBlogPrefs(slug: string, prefs: BlogPrefs | null): void {
	try {
		if (prefs) localStorage.setItem(storeKey(slug), JSON.stringify(prefs));
		else localStorage.removeItem(storeKey(slug));
	} catch {
		// storage refused: the setting lasts for this window only
	}
}
