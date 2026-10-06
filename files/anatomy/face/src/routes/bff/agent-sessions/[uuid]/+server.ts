/** BFF · one agent session, if it is the caller's (face-wing.yml §3: else 404).
 *
 * Projects the session row only. Threads and iterations stay in Wing until the
 * converse surface (I1) decides which of them a user may read.
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { agentSessions, wingBffConfigured, UpstreamError } from '$lib/server/upstream';
import { projectSession } from '$lib/agents/sessions';

const UUID = /^[0-9a-f-]{36}$/;

export const GET: RequestHandler = async ({ locals, params }) => {
	if (!wingBffConfigured())
		throw error(503, 'NOS_WING_BFF_TOKEN is not set on the face container.');
	if (!UUID.test(params.uuid)) throw error(404, 'not found');
	let raw: unknown;
	try {
		raw = await agentSessions.get(locals.identity, params.uuid);
	} catch (e) {
		if (e instanceof UpstreamError && [401, 403, 404].includes(e.status)) {
			throw error(e.status, e.message);
		}
		throw error(502, 'Wing did not answer');
	}
	const session = projectSession((raw as { session?: unknown } | null)?.session);
	if (!session) throw error(404, 'not found');
	return json({ session });
};
