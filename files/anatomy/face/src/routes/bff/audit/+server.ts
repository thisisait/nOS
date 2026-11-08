/** BFF · the audit chain's cached verdict for the Anatomy Wing view (row wing-inc2-agents-timeline),
 *  Tier 1. Chain off is a stated answer (`chain: 'off'`), never "ok"; Wing unreachable is a 502. */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { UpstreamError, wingAuditVerify, wingBffConfigured } from '$lib/server/upstream';
import { canViewAnatomy } from '$lib/security/tier';

export const GET: RequestHandler = async ({ locals }) => {
	if (!canViewAnatomy(locals.identity?.groups))
		throw error(403, 'The audit verdict is the admin tier.');
	if (!wingBffConfigured())
		throw error(503, 'NOS_WING_BFF_TOKEN is not set on the face container.');
	try {
		const v = (await wingAuditVerify(locals.identity)) as Record<string, unknown>;
		const pick = (k: string) => (k in v ? v[k] : null);
		return json({
			chain: pick('chain'),
			known: pick('known'),
			ok: pick('ok'),
			checked: pick('checked'),
			verifiedAt: pick('verified_at'),
			note: pick('note')
		});
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw error(502, 'Wing did not answer');
	}
};
