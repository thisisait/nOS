/** BFF · the menubar's system pulse. READ-ONLY, Tier-1 only.
 *
 * One request, because the menubar polls forever on every session. Reducing
 * three upstream calls to one line happens here rather than in the browser, so
 * a partial failure is reconciled once and in a place that can say so.
 *
 * A non-admin gets `visible: false` and a 200 — NOT a 403. The menubar is not
 * asking for permission, it is asking whether there is anything to show; a 403
 * would be an error state rendered forever in the corner of every tier-3
 * user's screen, which teaches everyone to ignore the corner.
 */
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import {
	pulseJobs,
	pulseRunSummary,
	wingNotifications,
	boneHealth,
	wingApiConfigured
} from '$lib/server/upstream';
import { projectSnapshot } from '$lib/anatomy/pulse';
import { projectNotification, isContested, isUnreadWork } from '$lib/anatomy/wing';
import { canViewAnatomy } from '$lib/security/tier';
import { QUIET, type SystemStatus } from '$lib/anatomy/status';

export const GET: RequestHandler = async ({ locals }) => {
	if (!canViewAnatomy(locals.identity?.groups)) {
		return json(QUIET);
	}
	if (!wingApiConfigured()) {
		// Not an error and not zeroes: nothing was checked, and the menubar
		// must be able to say that rather than looking calm.
		return json({ ...QUIET, visible: true, error: 'NOS_WING_API_TOKEN is not set' });
	}

	const out: SystemStatus = { ...QUIET, visible: true };

	try {
		const snap = projectSnapshot(await pulseJobs(), await pulseRunSummary());
		out.failing = snap.counts.failing;
		out.overdue = snap.counts.overdue;
		out.never = snap.counts.never;
	} catch (e) {
		out.error = e instanceof Error ? e.message : 'Wing pulse did not answer';
	}

	try {
		const raw = (await wingNotifications({ limit: '60' })) as {
			notifications?: Record<string, unknown>[];
		};
		const notes = (raw.notifications ?? []).map(projectNotification);
		out.alerts = notes.filter(
			(n) => isUnreadWork(n) && ['high', 'critical'].includes(n.severity.toLowerCase())
		).length;
		out.contested = notes.filter(isContested).length;
	} catch (e) {
		// Keep the first error rather than the last: whichever upstream failed
		// first is the one worth naming, and overwriting it hides a cascade.
		out.error ??= e instanceof Error ? e.message : 'Wing inbox did not answer';
	}

	try {
		const h = (await boneHealth()) as { status?: string };
		out.boneAlive = typeof h.status === 'string' && h.status.length > 0;
	} catch {
		// Bone being down is DATA, not an error in building the summary — it is
		// exactly the thing the menubar exists to surface.
		out.boneAlive = false;
	}

	return json(out);
};
