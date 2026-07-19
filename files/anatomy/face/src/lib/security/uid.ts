/**
 * Stable per-user partition key.
 *
 * Authentik's `X-Authentik-uid` is a RANDOM hash regenerated whenever the user
 * is re-provisioned — e.g. every `blank=true` wipes Authentik's DB, so the same
 * person logs back in under a NEW uid. Keying the user's file tree
 * (`tenants/<slug>/users/<uid>/…`) + user-state DB on that random uid therefore
 * ORPHANS all their data on every blank (the tree survives under the old uid;
 * the new uid sees an empty tree; KEAP's whole-tree mirror re-surfaces the
 * orphan). See docs/plans/blank-uninstall-managed-resources.md §2c.
 *
 * Fix: derive a STABLE uid from the username (then email local-part), which
 * forward-auth already provides and which survives re-provisioning. Pure + no
 * server imports so it runs in node/vitest.
 */

/**
 * Slugify to a filesystem- and KEAP-safe segment. THE CANONICAL CONTRACT (KEAP's
 * `canonicalUid` must reproduce this byte-for-byte so the file-mirror owner
 * [= directory name] equals the per-user-row owner):
 *   1. NFKD normalize, then STRIP combining diacritical marks (U+0300–U+036F) —
 *      so `Pázny`→`pazny`, `Šárka`→`sarka` (Czech folds to ASCII). The accents are
 *      DROPPED, never turned into a separator.
 *   2. lowercase.
 *   3. every run of non-`[a-z0-9]` (spaces, dots, `_`, `@`, leftover non-ASCII…)
 *      → a single `-`.
 *   4. trim leading/trailing `-`; cap at 64; re-trim.
 * Result is `[a-z0-9-]` with no leading/trailing/double dash → satisfies Bone's
 * `_user_root` guard (never `/`, `.`, `..`, or a leading dot).
 */
export function slugifyUid(s: string): string {
	return s
		.normalize('NFKD')
		.replace(/[̀-ͯ]/g, '') // strip combining diacritics (Pázny→Pazny)
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '-') // everything else → single dash
		.replace(/^-+|-+$/g, '')
		.slice(0, 64)
		.replace(/-+$/g, '');
}

/**
 * The canonical, blank-stable uid for a user. Prefers the slugified username,
 * then the email local-part, and only as a last resort the (sanitized) raw
 * Authentik uid — so an identity with no stable claim still gets a usable key
 * rather than crashing. Returns '' only when every input is empty (anonymous).
 */
export function canonicalUid(username: string, email: string, rawUid: string): string {
	const fromName = slugifyUid(username || '');
	if (fromName) return fromName;
	const local = (email || '').split('@')[0] || '';
	const fromEmail = slugifyUid(local);
	if (fromEmail) return fromEmail;
	return slugifyUid(rawUid || '');
}
