/** BFF · the root CA digest for Control Panel -> Identity (row
 *  nos-root-ca-fingerprint-second-channel). Every signed-in person: the digest is public; the
 *  gate is this tier, Bone's route is public but off the edge. Projection = the four fields. */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { boneRootCa, UpstreamError } from '$lib/server/upstream';
import { projectRootCa } from '$lib/security/rootCa';

export const GET: RequestHandler = async ({ locals }) => {
	if (!locals.identity.authenticated) throw error(401, 'unauthenticated');
	try {
		return json(projectRootCa(await boneRootCa()));
	} catch (e) {
		// The status only: Bone's error body is not this panel's to show.
		const why = e instanceof UpstreamError ? `Bone answered ${e.status}` : 'Bone did not answer';
		return json(projectRootCa({ trusted: { unknown: why }, served: { unknown: 'not compared' } }));
	}
};
