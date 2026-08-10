/** BFF · the run screen's ONE write: run a declared gate set.
 *
 * The machinery doctrine bounds this precisely: a button may RUN something
 * already declared; it may never ALTER what is declared. Bone's
 * POST /api/v1/loop/judge is exactly that surface — 202-async, and the only
 * input that selects work is the gate-set NAME ("no parameter that supplies,
 * hints at, or overrides a result"). The verdict lands in the ledger written
 * by the engine, so the reader records the outcome; this button only
 * requested it.
 *
 * REFUSALS THIS MODULE ADDS (each visible to the caller, enumerated in the
 * run screen's UI):
 *   403  caller below Tier-1 (server-side; a hidden button is not access control)
 *   400  any body key other than `gate_set` — refuse, don't strip: a stripped
 *        key trains callers to send garbage. `proposal_uuid` in particular is
 *        NOT forwarded — judging a proposal is the loop engine's ceremony,
 *        not a browser act.
 *   409  a gate set declared `unattended: false` (today: `full`) — it
 *        contains judges that require an attended host.
 *   404  unknown gate set — Bone's own refusal, passed through.
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { loop, loopConfigured, UpstreamError } from '$lib/server/upstream';
import { canViewAnatomy } from '$lib/security/tier';
import graph from '$lib/anatomy/anatomy-graph.json';

/** The committed gate-set declarations, from the same artifact the definition
 *  screen renders — state/judge-sets.yml by way of the anatomy graph. */
function gatesetUnattended(name: string): boolean | null {
	const node = (graph.nodes as Record<string, { kind?: string; unattended?: boolean }>)[
		`gateset:${name}`
	];
	if (!node || node.kind !== 'gateset') return null;
	return node.unattended === true;
}

export const POST: RequestHandler = async ({ locals, request }) => {
	if (!canViewAnatomy(locals.identity?.groups)) {
		throw error(403, 'Running a gate set requires the admin tier.');
	}
	if (!loopConfigured()) {
		throw error(503, 'BONE_LOOP_JUDGE_TOKEN is not set on the face container.');
	}
	let body: Record<string, unknown>;
	try {
		body = (await request.json()) as Record<string, unknown>;
	} catch {
		throw error(400, 'body must be JSON');
	}
	const keys = Object.keys(body);
	if (keys.length !== 1 || keys[0] !== 'gate_set' || typeof body.gate_set !== 'string') {
		throw error(
			400,
			"body accepts exactly {gate_set}. proposal_uuid is deliberately not forwarded — judging a proposal is the loop engine's ceremony, not a browser act."
		);
	}
	const gateSet = body.gate_set;
	const unattended = gatesetUnattended(gateSet);
	if (unattended === false) {
		throw error(
			409,
			`gate set '${gateSet}' is declared unattended:false — it contains judges that require an attended host, so a browser button may not fire it.`
		);
	}
	try {
		return json(await loop.judge(gateSet), { status: 202 });
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status === 404 ? 404 : 502, e.message);
		throw error(502, 'Bone did not answer');
	}
};

/** Status poll for a 202'd run: GET /bff/loop/judge?job_id=… */
export const GET: RequestHandler = async ({ locals, url }) => {
	if (!canViewAnatomy(locals.identity?.groups)) {
		throw error(403, 'The Anatomy view requires the admin tier.');
	}
	if (!loopConfigured()) {
		throw error(503, 'BONE_LOOP_JUDGE_TOKEN is not set on the face container.');
	}
	const jobId = url.searchParams.get('job_id');
	if (!jobId) throw error(400, 'job_id is required');
	try {
		return json(await loop.judgeStatus(jobId));
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status === 404 ? 404 : 502, e.message);
		throw error(502, 'Bone did not answer');
	}
};
