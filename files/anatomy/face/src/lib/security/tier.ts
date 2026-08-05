/**
 * RBAC tier helpers — the shell-side mirror of the Authentik group → tier map.
 *
 * DataTable WRITES (creating tables, upserting rows) are a privileged action:
 * the config catalog + the Apps/Systems tables are shared state. Only manager+
 * tiers may write; everyone authenticated may read. This is decided server-side
 * in the BFF from the edge-trusted `identity.groups` — never from a client claim.
 *
 * Pure + unit-tested; no server imports so it runs in node/vitest.
 */

/** Authentik groups that grant DataTable write access (Tier 1 + Tier 2). */
export const WRITE_GROUPS = ['nos-admins', 'nos-providers', 'nos-managers'] as const;

/** True when the caller's groups include any write-tier group. */
export function canWriteTables(groups: readonly string[] | undefined): boolean {
	if (!groups || groups.length === 0) return false;
	const set = new Set(groups.map((g) => g.trim().toLowerCase()));
	return WRITE_GROUPS.some((g) => set.has(g));
}

/** Authentik groups that grant the Tier-1 admin surfaces. */
export const ADMIN_GROUPS = ['nos-admins', 'nos-providers'] as const;

/**
 * True for Tier-1 (admin/provider) callers.
 *
 * The Anatomy view gates on this rather than on the write tier because what it
 * shows is operational internals — schedules, failure output, which jobs have
 * never run. That is administrator information even though every request behind
 * it is a GET; "read-only" bounds the blast radius of a bug, not the
 * sensitivity of the answer.
 */
export function canViewAnatomy(groups: readonly string[] | undefined): boolean {
	if (!groups || groups.length === 0) return false;
	const set = new Set(groups.map((g) => g.trim().toLowerCase()));
	return ADMIN_GROUPS.some((g) => set.has(g));
}
