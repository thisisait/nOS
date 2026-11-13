/** BFF · "Awaiting you" (row face-app-awaiting): GET only, Tier 1 (Wing answers questions only to Tier 1).
 *
 * Merges Wing's open agent questions and its unread notifications (critical/high) through the face-bff
 * token, server side, plus the caller's own open Iris cards through a read hello (askOnce: never their
 * live Iris tab, 3 s, cached 15 s per uid, a failure is `unknown`, the Wing half still answers), Bone's
 * unlanded loop proposals (BONE_LOOP_JUDGE_TOKEN, read scope; unset or failed = `unknown`), and
 * returns id/kind/title/since only (lib/awaiting/project.ts). Nothing here acts:
 * the person answers in the Inbox app. 403 below Tier 1, 503 the face-bff token not wired.
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import {
	UpstreamError,
	loop,
	loopConfigured,
	wingBffConfigured,
	wingNotifications,
	wingQuestions
} from '$lib/server/upstream';
import { canViewAnatomy } from '$lib/security/tier';
import { projectAwaiting } from '$lib/awaiting/project';
import { askOnce } from '$lib/server/thalamus';
import type { Identity } from '$lib/contracts';

const CARDS_MS = 3_000;
const CACHE_MS = 15_000;
/** Per uid, answers AND refusals, so the dock's poll neither hammers a down thalamus nor re-asks.
 *  The in-flight ask is cached, not only its value: parallel polls share one relay link (review 11-13). */
const cards = new Map<string, { at: number; p: Promise<unknown[] | string> }>();

function irisCards(who: Identity): Promise<unknown[] | string> {
	const hit = cards.get(who.uid);
	if (hit && Date.now() - hit.at < CACHE_MS) return hit.p;
	const p = askCards(who);
	cards.set(who.uid, { at: Date.now(), p });
	return p;
}

async function askCards(who: Identity): Promise<unknown[] | string> {
	const got = await askOnce(who, JSON.stringify({ t: 'approvals_open' }), CARDS_MS);
	let v: unknown[] | string = 'the thalamus gave an answer that is not approvals_open';
	if ('why' in got) v = got.why;
	else {
		try {
			const m = JSON.parse(got.line) as { t?: unknown; items?: unknown; reason?: unknown };
			if (m.t === 'approvals_open' && Array.isArray(m.items)) v = m.items;
			else if (m.t === 'refused') v = `refused: ${String(m.reason ?? '')}`;
		} catch {
			v = 'the thalamus answered a line that is not JSON';
		}
	}
	return v;
}

/** Bone's awaiting answer, or why there is none; never throws (the Wing half still answers). */
async function loopProposals(): Promise<unknown> {
	if (!loopConfigured()) return 'BONE_LOOP_JUDGE_TOKEN is not set on the face container';
	try {
		return await loop.awaiting();
	} catch (e) {
		return e instanceof UpstreamError ? `Bone answered ${e.status}` : 'Bone did not answer';
	}
}

export const GET: RequestHandler = async ({ locals }) => {
	if (!canViewAnatomy(locals.identity?.groups))
		throw error(403, 'What awaits the operator is the admin tier.');
	if (!wingBffConfigured())
		throw error(503, 'NOS_WING_BFF_TOKEN is not set on the face container.');
	try {
		const [q, n, c, p] = (await Promise.all([
			wingQuestions(locals.identity),
			wingNotifications(locals.identity, { unread_only: '1', limit: '200' }),
			irisCards(locals.identity),
			loopProposals()
		])) as [{ questions?: unknown }, { notifications?: unknown }, unknown[] | string, unknown];
		return json(projectAwaiting(q.questions, n.notifications, c, p));
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw error(502, 'Wing did not answer');
	}
};
