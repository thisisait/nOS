/**
 * The tier each BFF route needs (row face-app-min-tier, layer 2 of three: the launcher hides,
 * the BFF refuses, Wing refuses again). Measured 2026-11-08 from the routes' own guards:
 * tier 1 routes call canViewAnatomy and answer 403; tier 4 routes serve any signed-in person
 * and the owner is decided further on (uid pinned for vfs/userstate, Wing scopes sessions to
 * their owner, KEAP visibility for tables, the hub filters by tierOf, Iris by the identity map).
 * Gate: bffTiers.test.ts maps every src/routes/bff route here and reads each tier-1 guard.
 */
import type { Tier } from './tier';

export const BFF_TIERS: Record<string, Tier> = {
	'/bff/awaiting': 1,
	'/bff/bone': 1,
	'/bff/inbox': 1,
	'/bff/loop': 1,
	'/bff/loop/judge': 1,
	'/bff/pulse': 1,
	'/bff/pulse/run': 1,
	'/bff/wing': 1,
	'/bff/agent-sessions/[uuid]': 4,
	// Wing narrows it: Tier 1 stops any run, anyone else their own (operator 2026-11-08).
	'/bff/agent-sessions/[uuid]/cancel': 4,
	'/bff/agents': 1,
	'/bff/audit': 1,
	'/bff/agents/[name]/sessions': 4,
	'/bff/ask': 4,
	'/bff/config': 4,
	// the public root CA digest (Control Panel -> Identity); Bone's route is off the edge.
	'/bff/estate/root-ca': 4,
	'/bff/hub': 4,
	'/bff/iris/send': 4,
	'/bff/iris/stream': 4,
	// status answers everyone; the admin-only parts (pulse, Wing notifications) only for tier 1.
	'/bff/status': 4,
	'/bff/tables': 4,
	'/bff/userstate': 4,
	'/bff/vfs': 4
};

/** A FaceApp.apiScopes name -> the routes it calls; an app's minTier must reach each. */
export const SCOPE_ROUTES: Record<string, string[]> = {
	awaiting: ['/bff/awaiting'],
	agents: ['/bff/agents', '/bff/agents/[name]/sessions', '/bff/agent-sessions/[uuid]/cancel'],
	config: ['/bff/config'],
	inbox: ['/bff/inbox'],
	iris: ['/bff/iris/send', '/bff/iris/stream'],
	pulse: ['/bff/pulse'],
	tables: ['/bff/tables'],
	userstate: ['/bff/userstate'],
	vfs: ['/bff/vfs']
};

/** The strictest tier an app's scopes need (1 is strictest); 4 when it calls none. */
export function scopeTier(scopes: readonly string[] | undefined): Tier {
	let t: Tier = 4;
	for (const s of scopes ?? [])
		for (const r of SCOPE_ROUTES[s] ?? []) t = Math.min(t, BFF_TIERS[r] ?? 4) as Tier;
	return t;
}
