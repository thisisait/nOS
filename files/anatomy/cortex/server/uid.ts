/**
 * canonicalUid — the ONE stable per-user key.
 *
 * KEAP keys two things per user: DB ROWS (progress, todos, hand-made objects —
 * from the identity middleware) and fs-mirror OBJECTS (from the `<uid>/` folder
 * name under KEAP_USER_FILES_DIR). Historically the rows keyed on Authentik's
 * random X-Authentik-Uid while the files keyed on the folder name (a username),
 * so a user's own files never matched their row scope. This unifies BOTH on a
 * canonical slug of the username, so rows ⇔ files share one owner.
 *
 * BYTE-EXACT port of the nOS face BFF contract ($lib/security/uid.ts, commit
 * e5c3734f, 2026-07-19) — the two must agree or the mirror owner (folder name,
 * slugified by Bone) and the row owner (header, slugified here) diverge again:
 *
 *   source priority : username → email local-part → uid
 *   transform       : NFKD → strip combining marks U+0300–U+036F → toLowerCase
 *                     → each [^a-z0-9]+ run → single '-' → trim '-' → cap 64
 *                     → re-trim '-'
 *
 * Diacritics FOLD, they don't dash-split: 'Pázny' → 'pazny' (the combining
 * accent is stripped, not turned into '-'). '.', '_', '@', spaces → '-'. Only
 * [a-z0-9] survives as content; '-' is the sole separator. Non-decomposable
 * letters (ß, ł) have no NFKD mapping, so they fall to '-' (accepted edge).
 */

/** The slug transform alone (no source fallback). Exported for the unit vectors. */
export function slugifyUid(raw: string | null | undefined): string {
  return (raw ?? '')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '') // strip combining diacritical marks
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-') // any run of non-alphanumerics → one dash
    .replace(/^-+|-+$/g, '') // trim leading/trailing dashes
    .slice(0, 64) // cap
    .replace(/^-+|-+$/g, ''); // re-trim in case the cap left a dangling dash
}

/**
 * Resolve the canonical owner key from the identity signals, in priority order.
 * Every branch is slugified, so a caller can pass raw header values (or a raw
 * folder name as `username`) and always get a canonical, filesystem-safe key.
 */
export function canonicalUid(
  username?: string | null,
  email?: string | null,
  uid?: string | null,
): string {
  const fromUsername = slugifyUid(username);
  if (fromUsername) return fromUsername;
  // Email fallback keys on the LOCAL PART only (before '@'), then slugifies it.
  const fromEmail = slugifyUid((email ?? '').split('@')[0]);
  if (fromEmail) return fromEmail;
  return slugifyUid(uid);
}
