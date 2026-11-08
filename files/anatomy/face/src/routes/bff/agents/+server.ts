/** BFF · the agent roster for the face Agents app (row wing-inc2-agents-timeline), Tier 1.
 *  Projected: name, version, description, has_outcome, or the load error; nothing else. */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { UpstreamError, wingAgents, wingBffConfigured } from '$lib/server/upstream';
import { canViewAnatomy } from '$lib/security/tier';
import { projectRoster } from '$lib/agents/roster';

export const GET: RequestHandler = async ({ locals }) => {
	if (!canViewAnatomy(locals.identity?.groups))
		throw error(403, 'The agent roster is the admin tier.');
	if (!wingBffConfigured())
		throw error(503, 'NOS_WING_BFF_TOKEN is not set on the face container.');
	try {
		return json({ agents: projectRoster(await wingAgents(locals.identity)) });
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw error(502, 'Wing did not answer');
	}
};
