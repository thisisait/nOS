/** BFF · Anatomy → Wing view. READ-ONLY, Tier-1 only.
 *
 * GET is the only exported handler; SvelteKit answers 405 for the rest, so
 * read-only is the module's shape rather than a rule someone remembers.
 *
 * `?thread=<actor_action_id>` narrows both lists to one logical action. That
 * parameter is the reason Anatomy is one app: a Pulse run and the events it
 * produced share the value, and following it across two apps loses your place.
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { wingEvents, wingNotifications, wingApiConfigured } from '$lib/server/upstream';
import { projectWing } from '$lib/anatomy/wing';
import { canViewAnatomy } from '$lib/security/tier';

export const GET: RequestHandler = async ({ locals, url }) => {
	if (!canViewAnatomy(locals.identity?.groups)) {
		throw error(403, 'The Anatomy view requires the admin tier.');
	}
	if (!wingApiConfigured()) {
		return json({
			configured: false,
			note: 'NOS_WING_API_TOKEN is not set on the face container, so Wing’s events and inbox cannot be read. Nothing was checked.'
		});
	}

	const thread = url.searchParams.get('thread') ?? '';
	const type = url.searchParams.get('type') ?? '';
	const eventParams: Record<string, string> = {};
	const notifParams: Record<string, string> = {};
	if (thread) {
		eventParams.actor_action_id = thread;
		notifParams.actor_action_id = thread;
	}
	if (type) eventParams.type = type;

	try {
		const events = await wingEvents(eventParams);
		const notifications = await wingNotifications(notifParams);
		return json({ configured: true, thread, ...projectWing(events, notifications) });
	} catch (e) {
		return json({
			configured: true,
			thread,
			error: e instanceof Error ? e.message : 'Wing did not answer',
			events: [],
			eventsTotal: 0,
			notifications: [],
			contestedDeliveries: 0
		});
	}
};
