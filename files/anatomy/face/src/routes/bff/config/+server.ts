/** BFF · client-safe config. Exposes non-secret URLs the browser needs (e.g.
 *  the KEAP explore URL the "Explore" app iframes). No tokens here — anything
 *  returned is shipped to the client. */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { keapExploreUrl } from '$lib/server/upstream';

export const GET: RequestHandler = async ({ locals }) => {
	if (!locals.identity.authenticated) throw error(401, 'unauthenticated');
	return json({ keapExploreUrl: keapExploreUrl() });
};
