import type { LayoutServerLoad } from './$types';

/** Surface the edge-trusted identity to the page (read-only). */
export const load: LayoutServerLoad = async ({ locals }) => {
	return { identity: locals.identity };
};
