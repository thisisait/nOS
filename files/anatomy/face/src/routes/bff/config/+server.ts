/** BFF · client-safe config. Exposes non-secret URLs the browser needs (e.g.
 *  the KEAP explore URL the "Explore" app iframes). No tokens here — anything
 *  returned is shipped to the client. */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { keapExploreUrl } from '$lib/server/upstream';
import { canWriteTables } from '$lib/security/tier';

export const GET: RequestHandler = async ({ locals }) => {
	if (!locals.identity.authenticated) throw error(401, 'unauthenticated');
	return json({
		keapExploreUrl: keapExploreUrl(),
		// Manager+ may create tables / upsert rows. Server-derived from the
		// edge-trusted identity — the UI only uses it to show/hide the New-table
		// button; the BFF POST re-enforces it regardless.
		canWriteTables: canWriteTables(locals.identity.groups)
	});
};
