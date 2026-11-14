/** BFF · Anatomy → Upgrades view. READ-ONLY, Tier-1 only.
 *
 * GET is the only exported handler; SvelteKit answers 405 for the rest, so no queue, plan, promote or
 * apply verb exists in the face: they stay in Wing. Wing re-checks Tier 1 itself (the three actions are
 * its presenter's $bffOperatorReads). The upstream JSON never passes through: projectUpgrades copies a
 * fixed field list (no recipes[], steps, reset, env or raw record).
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import {
	wingUpgrades,
	wingUpgradesPlanned,
	wingUpgradesHistory,
	wingBffConfigured,
	wingPublicUrl
} from '$lib/server/upstream';
import { projectUpgrades } from '$lib/anatomy/upgrades';
import { canViewAnatomy } from '$lib/security/tier';

export const GET: RequestHandler = async ({ locals }) => {
	if (!canViewAnatomy(locals.identity?.groups)) {
		throw error(403, 'The Anatomy view requires the admin tier.');
	}
	const wingUrl = wingPublicUrl();
	if (!wingBffConfigured()) {
		return json({
			configured: false,
			wingUrl,
			note: 'NOS_WING_BFF_TOKEN is not set on the face container, so Wing’s upgrade matrix cannot be read. Nothing was checked.'
		});
	}
	try {
		const [matrix, planned, history] = await Promise.all([
			wingUpgrades(locals.identity),
			wingUpgradesPlanned(locals.identity),
			wingUpgradesHistory(locals.identity)
		]);
		return json({ configured: true, wingUrl, ...projectUpgrades(matrix, planned, history) });
	} catch (e) {
		return json({
			configured: true,
			wingUrl,
			error: e instanceof Error ? e.message : 'Wing did not answer',
			services: [],
			planned: [],
			history: []
		});
	}
};
