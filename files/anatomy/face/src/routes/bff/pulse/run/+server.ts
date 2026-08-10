/** BFF · the Pulse half of the on-demand surface: run a declared job NOW.
 *
 * §4b semantics end-to-end: this route forwards a body allow-list of exactly
 * `{job_id}` to Wing's `POST /pulse_jobs/<id>/run-now`, which edits ONE row
 * (next_fire_at = now) and records who asked. The daemon remains the only
 * executor — the run appearing in the runs feed is the daemon's statement,
 * not this button's. No env override, no command override, no synchronous
 * execution exists anywhere on this path.
 *
 * Refusals (each surfaced verbatim to the UI):
 *   403  caller below Tier-1 (server-side re-check)
 *   400  any body key other than `job_id` — refused, not stripped
 *   409  paused job (Wing's refusal, passed through with paused_reason)
 *   404  unknown job (Wing's refusal)
 *   503  Wing token not wired
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { pulseRunNow, wingApiConfigured, UpstreamError } from '$lib/server/upstream';
import { canViewAnatomy } from '$lib/security/tier';

export const POST: RequestHandler = async ({ locals, request }) => {
	if (!canViewAnatomy(locals.identity?.groups)) {
		throw error(403, 'Running a pulse job requires the admin tier.');
	}
	if (!wingApiConfigured()) {
		throw error(503, 'NOS_WING_API_TOKEN is not set on the face container.');
	}
	let body: Record<string, unknown>;
	try {
		body = (await request.json()) as Record<string, unknown>;
	} catch {
		throw error(400, 'body must be JSON');
	}
	const keys = Object.keys(body);
	if (keys.length !== 1 || keys[0] !== 'job_id' || typeof body.job_id !== 'string') {
		throw error(400, 'body accepts exactly {job_id} — env/command overrides are refused by design');
	}
	try {
		return json(await pulseRunNow(body.job_id), { status: 202 });
	} catch (e) {
		if (e instanceof UpstreamError) {
			// Wing's own refusals pass through with their status intact —
			// 409 paused and 404 unknown are answers, not transport faults.
			throw error(e.status === 404 || e.status === 409 ? e.status : 502, e.message);
		}
		throw error(502, 'Wing did not answer');
	}
};
