/**
 * RBAC tier helpers — the shell-side mirror of the Authentik group → tier map.
 *
 * DataTable WRITES (creating tables, upserting rows) are manager+. READS honour
 * the table's KEAP visibility grade (fail closed). Decided server-side in the
 * BFF from edge-trusted `identity.groups` — never from a client claim.
 *
 * Pure + unit-tested; no server imports so it runs in node/vitest.
 */

/** Authentik groups that grant DataTable write access (Tier 1 + Tier 2). */
export const WRITE_GROUPS = ['nos-admins', 'nos-providers', 'nos-managers'] as const;

/** Authentik groups that grant the Tier-1 admin surfaces. */
export const ADMIN_GROUPS = ['nos-admins', 'nos-providers'] as const;

/** Lower rank = more privileged. Mirrors keap-contracts/visibility VISIBILITY_MIN_RANK. */
const GROUP_RANK: Record<string, number> = {
	'nos-providers': 1,
	'nos-admins': 1,
	'nos-managers': 2,
	'nos-users': 3,
	'nos-guests': 4
};

const VISIBILITY_READ_RANK: Record<string, number> = {
	private: 0,
	system: 0,
	'tier-managers': 2,
	'tier-users': 3,
	'tier-guests': 4,
	shared: 99
};

function groupSet(groups: readonly string[] | undefined): Set<string> {
	return new Set((groups ?? []).map((g) => g.trim().toLowerCase()).filter(Boolean));
}

function callerRank(groups: readonly string[] | undefined): number | undefined {
	let best: number | undefined;
	for (const g of groupSet(groups)) {
		const r = GROUP_RANK[g];
		if (r !== undefined && (best === undefined || r < best)) best = r;
	}
	return best;
}

/** True when the caller's groups include any write-tier group. */
export function canWriteTables(groups: readonly string[] | undefined): boolean {
	const set = groupSet(groups);
	return WRITE_GROUPS.some((g) => set.has(g));
}

/**
 * True when the caller may READ a table of this visibility grade.
 * Unknown / missing / private / system (non-admin) fail closed.
 * `shared` is any authenticated caller (the BFF already requires identity).
 */
export function canReadTable(
	visibility: string | undefined | null,
	groups: readonly string[] | undefined
): boolean {
	if (typeof visibility !== 'string' || !visibility) return false;
	const min = VISIBILITY_READ_RANK[visibility];
	if (min === undefined) return false;
	if (min === 0) return canViewAnatomy(groups);
	if (min === 99) return true;
	const rank = callerRank(groups);
	return rank !== undefined && rank <= min;
}

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
	const set = groupSet(groups);
	return ADMIN_GROUPS.some((g) => set.has(g));
}
