/** BFF · an end user's agent sessions (files/anatomy/contracts/face-wing.yml, wire).
 *
 * GET lists, POST opens. Both go to Wing AS the hook-pinned uid through the
 * `face-bff` bearer; Wing stamps actor_id = user:<uid> and narrows the list.
 * The browser sends at most {prompt}; it never names a uid, actor or vault.
 * Wing's 401/403/404 pass through as answers; anything else is a 502.
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { agentSessions, wingBffConfigured, UpstreamError } from '$lib/server/upstream';
import { AGENT_NAME, parseOpenBody, projectOpened, projectSessionList } from '$lib/agents/sessions';

function guard(name: string): void {
	if (!wingBffConfigured())
		throw error(503, 'NOS_WING_BFF_TOKEN is not set on the face container.');
	if (!AGENT_NAME.test(name)) throw error(400, 'unknown agent name shape');
}

function upstream(e: unknown): never {
	if (e instanceof UpstreamError && [401, 403, 404].includes(e.status))
		throw error(e.status, e.message);
	throw error(502, 'Wing did not answer');
}

export const GET: RequestHandler = async ({ locals, params }) => {
	guard(params.name);
	try {
		return json({
			sessions: projectSessionList(await agentSessions.list(locals.identity, params.name))
		});
	} catch (e) {
		upstream(e);
	}
};

export const POST: RequestHandler = async ({ locals, params, request }) => {
	guard(params.name);
	let raw: unknown;
	try {
		raw = await request.json();
	} catch {
		throw error(400, 'body must be JSON');
	}
	const body = parseOpenBody(raw);
	if (typeof body === 'string') throw error(400, body);
	let opened;
	try {
		opened = projectOpened(await agentSessions.open(locals.identity, params.name, body));
	} catch (e) {
		upstream(e);
	}
	if (!opened) throw error(502, 'Wing answered without a session uuid');
	return json(opened, { status: 202 });
};
