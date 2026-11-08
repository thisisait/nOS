/** BFF · the face Inbox app (row wing-inc1-inbox-app): Wing's inbox for a Tier-1 person.
 *
 * GET   the unread notifications and the open agent questions, projected (lib/inbox/project.ts):
 *       never a reply token, its hash or a question's context.
 * POST  {op: 'read', uuid} marks one notification read; {op: 'answer', uuid, answer} answers one
 *       question as the person (Wing records user:<uid>, via face, and resolves it once).
 *
 * Refusals: 403 below Tier 1 (here, and again in Wing: both are operator verbs), 403 a POST that
 * is not same-origin JSON (SvelteKit's CSRF check covers form types only), 400 any other body,
 * 503 the face-bff token not wired. A lost answer is not an error: it comes back as `lost` with
 * the answer that won.
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import {
	UpstreamError,
	wingAnswer,
	wingBffConfigured,
	wingMarkRead,
	wingNotifications,
	wingQuestions
} from '$lib/server/upstream';
import { fromThisSite } from '$lib/server/thalamus';
import { canViewAnatomy } from '$lib/security/tier';
import { answerOutcome, projectNotifications, projectQuestions } from '$lib/inbox/project';

const UUID = /^[0-9a-z-]{1,64}$/;

function gate(groups: readonly string[] | undefined) {
	if (!canViewAnatomy(groups)) throw error(403, 'The inbox is the admin tier.');
	if (!wingBffConfigured())
		throw error(503, 'NOS_WING_BFF_TOKEN is not set on the face container.');
}

export const GET: RequestHandler = async ({ locals }) => {
	gate(locals.identity?.groups);
	try {
		const [q, n] = (await Promise.all([
			wingQuestions(locals.identity),
			wingNotifications(locals.identity, { unread_only: '1', limit: '200' })
		])) as [{ questions?: unknown }, { notifications?: unknown; total?: number }];
		return json({
			questions: projectQuestions(q.questions),
			notifications: projectNotifications(n.notifications),
			unread: typeof n.total === 'number' ? n.total : null
		});
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw error(502, 'Wing did not answer');
	}
};

export const POST: RequestHandler = async ({ locals, request, url }) => {
	gate(locals.identity?.groups);
	if (!fromThisSite(request, url, true)) throw error(403, 'not from this site');
	const type = (request.headers.get('content-type') ?? '').split(';')[0].trim().toLowerCase();
	if (type !== 'application/json') throw error(403, 'application/json only');
	let b: Record<string, unknown>;
	try {
		b = (await request.json()) as Record<string, unknown>;
	} catch {
		throw error(400, 'body must be JSON');
	}
	const uuid = typeof b.uuid === 'string' ? b.uuid : '';
	if (!UUID.test(uuid)) throw error(400, 'uuid is not an id');
	try {
		if (b.op === 'read' && Object.keys(b).length === 2) {
			await wingMarkRead(locals.identity, uuid);
			return json({ result: 'read', uuid });
		}
		if (b.op === 'answer' && Object.keys(b).length === 3 && typeof b.answer === 'string') {
			const answer = b.answer.trim();
			if (!answer || answer.length > 2000) throw error(400, 'an answer is 1-2000 chars, not blank');
			const r = await wingAnswer(locals.identity, uuid, answer);
			return json({ uuid, ...answerOutcome(r.status, r.body) });
		}
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw e;
	}
	throw error(400, "body is {op: 'read', uuid} or {op: 'answer', uuid, answer}");
};
