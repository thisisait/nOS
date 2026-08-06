/** BFF · Anatomy → Runs view, loop ledger. READ-ONLY, Tier-1 only.
 *
 * GET only — the one write this screen owns lives at /bff/loop/judge, a
 * separate module, so "this route reads" stays a property of the module's
 * shape. The response is a PROJECTION (`$lib/anatomy/loop`): Bone's list
 * surface already excludes `diff_text` at its SQL column list, and the
 * projection refuses it a second time — two locks, because the browser is on
 * the other side of this door.
 *
 * Failure modes, same vocabulary as /bff/pulse:
 *   configured:false  BONE_LOOP_JUDGE_TOKEN is not wired (deployment fact)
 *   error:<message>   Bone answered badly (upstream fact)
 *   empty lists       Bone answered fine and the ledger is genuinely small —
 *                     9 proposals / 19 judge runs / 13 verdicts on 2026-08-06
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { loop, loopConfigured } from '$lib/server/upstream';
import { projectLoop } from '$lib/anatomy/loop';
import { canViewAnatomy } from '$lib/security/tier';

export const GET: RequestHandler = async ({ locals }) => {
	if (!canViewAnatomy(locals.identity?.groups)) {
		throw error(403, 'The Anatomy view requires the admin tier.');
	}
	if (!loopConfigured()) {
		return json({
			configured: false,
			note: 'BONE_LOOP_JUDGE_TOKEN is not set on the face container, so the loop ledger cannot be read. Nothing was checked.'
		});
	}
	try {
		const proposals = await loop.proposals();
		const judgeRuns = await loop.judgeRuns();
		const verdicts = await loop.verdicts();
		return json({ configured: true, ...projectLoop(proposals, judgeRuns, verdicts) });
	} catch (e) {
		return json({
			configured: true,
			error: e instanceof Error ? e.message : 'Bone did not answer',
			proposals: [],
			judgeRuns: [],
			verdicts: [],
			counts: { proposals: 0, judgeRuns: 0, verdicts: 0 }
		});
	}
};
