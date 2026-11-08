/** BFF · stop one running agent session (row wing-inc2-agents-timeline, operator 2026-11-08).
 *  Any signed-in person; Wing decides whose: Tier 1 stops any run, anyone else only their own
 *  (another's answers 404, like an absent one), and a run that is not running is a 409. Same-
 *  origin POST with an empty body; the browser never names an actor. */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { agentSessions, wingBffConfigured, UpstreamError } from '$lib/server/upstream';
import { fromThisSite } from '$lib/server/thalamus';

const UUID = /^[0-9a-z-]{1,64}$/;

export const POST: RequestHandler = async ({ locals, params, request, url }) => {
	if (!locals.identity?.authenticated) throw error(401, 'unauthenticated');
	if (!wingBffConfigured())
		throw error(503, 'NOS_WING_BFF_TOKEN is not set on the face container.');
	if (!fromThisSite(request, url, true)) throw error(403, 'not from this site');
	if (!UUID.test(params.uuid)) throw error(404, 'not found');
	try {
		const r = (await agentSessions.cancel(locals.identity, params.uuid)) as Record<string, unknown>;
		return json({ uuid: params.uuid, status: r.status ?? 'cancelled' }, { status: 202 });
	} catch (e) {
		if (e instanceof UpstreamError && [401, 403, 404, 409].includes(e.status))
			throw error(e.status, e.message);
		throw error(502, 'Wing did not answer');
	}
};
