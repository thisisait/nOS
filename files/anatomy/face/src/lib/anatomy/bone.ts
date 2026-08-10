/**
 * Bone projection — liveness, the vein the face depends on, and an explicit
 * account of what this view is NOT allowed to see.
 *
 * THE THIRD ITEM IS THE INTERESTING ONE. Measured 2026-08-05: the face holds
 * `BONE_VFS_TOKEN`, a static bearer that Bone accepts for the `/api/v1/vfs`
 * router only. `/api/status`, `/api/services` and `/api/health/aggregate` are
 * scope-gated on an Authentik JWT carrying `nos:state:read`; presenting the VFS
 * token returns `401 invalid JWT header: Not enough segments`.
 *
 * A view could quietly omit those panels. It must not. An observability surface
 * that shows nothing where it cannot look teaches the operator that there is
 * nothing there — and the estate already lost ten days to a screen that was
 * green because it was measuring the wrong thing. So the gaps are DATA: named,
 * with the reason, on screen.
 *
 * `auth_ready` deserves the same treatment in the other direction. When it is
 * false, Bone's own JWT verifier never initialised, so every scope-gated
 * endpoint answers 503 — including the ones agents call. Bone still reports
 * `status: "ok"`, because liveness is all that field claims. Showing the two
 * side by side is the point.
 *
 * Pure — vitest runs it in node.
 */

export interface BoneGap {
	endpoint: string;
	/** Why this view cannot read it — a credential fact, not a failure. */
	reason: string;
}

export interface BoneSnapshot {
	/** Bone answered its liveness probe. */
	alive: boolean;
	/** Verbatim from Bone; it claims liveness only. */
	status: string;
	uptimeSeconds: number | null;
	/** False = Bone's JWT verifier never initialised → every scope-gated
	 *  endpoint answers 503, while /api/health keeps saying "ok". */
	authReady: boolean | null;
	/** Why `alive` is false, when it is. */
	error: string;
	/** The Bone↔face vein, probed rather than assumed. */
	vfs: { ok: boolean; detail: string };
	/** Surfaces this view is not credentialed for, stated rather than hidden. */
	gaps: BoneGap[];
}

/**
 * The scope-gated surfaces, named in one place.
 *
 * Hardcoded on purpose: this list is a claim about what the face's credential
 * cannot reach, and deriving it from a live 401 sweep would mean four extra
 * requests on every poll to re-learn something that only changes when the
 * deployment does.
 */
export const SCOPE_GATED: BoneGap[] = [
	{
		endpoint: 'GET /api/status',
		reason: 'requires an Authentik JWT with nos:state:read; the face holds a static VFS bearer'
	},
	{
		endpoint: 'GET /api/services',
		reason:
			'service registry — scope-gated since REM-110 (it is recon fuel: every internal host, port and version)'
	},
	{
		endpoint: 'GET /api/health/aggregate',
		reason:
			'per-service fan-out — same scope. Note it reports each service’s OWN /health, which is exactly the signal that stayed green for ten days behind a broken Kuma'
	}
];

interface RawHealth {
	status?: string;
	uptime?: number;
	auth_ready?: boolean;
}

export function projectBone(
	health: unknown,
	vfs: { ok: boolean; detail: string },
	error = ''
): BoneSnapshot {
	const h = (health ?? {}) as RawHealth;
	const alive = typeof h.status === 'string' && h.status.length > 0 && !error;
	return {
		alive,
		status: String(h.status ?? ''),
		uptimeSeconds: typeof h.uptime === 'number' ? h.uptime : null,
		authReady: typeof h.auth_ready === 'boolean' ? h.auth_ready : null,
		error,
		vfs,
		gaps: SCOPE_GATED
	};
}

/** "1d 14h", "3m" — a duration a human reads at a glance. */
export function humanUptime(seconds: number | null): string {
	if (seconds === null || seconds < 0) return 'unknown';
	if (seconds < 60) return `${seconds}s`;
	if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
	if (seconds < 86400)
		return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
	return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}
