/** BFF · Anatomy → Bone view. READ-ONLY, Tier-1 only.
 *
 * Two calls, both of which the face is actually credentialed for: Bone's
 * ungated liveness probe, and a `stat /` through the VFS bearer that proves the
 * Bone↔face vein carries traffic rather than merely existing.
 *
 * The scope-gated surfaces are NOT called. They would 401, and a panel that
 * renders a 401 as an empty list is the failure this app was built to catch —
 * so they are reported as declared gaps instead (see `$lib/anatomy/bone`).
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { boneHealth, boneVfsProbe } from '$lib/server/upstream';
import { projectBone } from '$lib/anatomy/bone';
import { canViewAnatomy } from '$lib/security/tier';

export const GET: RequestHandler = async ({ locals }) => {
	if (!canViewAnatomy(locals.identity?.groups)) {
		throw error(403, 'The Anatomy view requires the admin tier.');
	}

	const uid = locals.identity?.uid ?? '';
	let health: unknown = {};
	let err = '';
	try {
		health = await boneHealth();
	} catch (e) {
		err = e instanceof Error ? e.message : 'Bone did not answer /api/health';
	}
	// Probed even when liveness failed: the two can disagree, and which one
	// failed is the diagnosis.
	const vfs = uid ? await boneVfsProbe(uid) : { ok: false, detail: 'no uid on this request' };

	return json({ configured: true, ...projectBone(health, vfs, err) });
};
