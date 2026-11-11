/** BFF · "Awaiting you" (row face-app-awaiting): GET only, Tier 1 (Wing answers questions only to Tier 1).
 *
 * Merges Wing's open agent questions and its unread notifications (critical/high) through the face-bff
 * token, server side, and returns id/kind/title/since only (lib/awaiting/project.ts). Nothing here acts:
 * the person answers in the Inbox app. 403 below Tier 1, 503 the face-bff token not wired.
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import {
	UpstreamError,
	wingBffConfigured,
	wingNotifications,
	wingQuestions
} from '$lib/server/upstream';
import { canViewAnatomy } from '$lib/security/tier';
import { projectAwaiting } from '$lib/awaiting/project';

export const GET: RequestHandler = async ({ locals }) => {
	if (!canViewAnatomy(locals.identity?.groups))
		throw error(403, 'What awaits the operator is the admin tier.');
	if (!wingBffConfigured())
		throw error(503, 'NOS_WING_BFF_TOKEN is not set on the face container.');
	try {
		const [q, n] = (await Promise.all([
			wingQuestions(locals.identity),
			wingNotifications(locals.identity, { unread_only: '1', limit: '200' })
		])) as [{ questions?: unknown }, { notifications?: unknown }];
		return json(projectAwaiting(q.questions, n.notifications));
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw error(502, 'Wing did not answer');
	}
};
