/**
 * Wing projection — events and the notification inbox.
 *
 * WHY THESE TWO AND NOT THE WHOLE OF WING. Wing UI already owns upgrades,
 * agents, migrations and the operator's own timeline, and it owns them well
 * enough that the operator says so. Duplicating them here would be a second
 * place to keep correct. What the FACE adds is the thread: an event carries
 * `actor_action_id`, a Pulse run carries the same value, and following one to
 * the other across two apps means losing your place. That is the entire
 * argument for Anatomy being one app.
 *
 * The inbox is here for a narrower reason. A notification row records
 * `ntfy_dispatched_at` / `mail_dispatched_at` — stamps written by the SENDER.
 * This estate has repeatedly found markers written by the code that attempted
 * the work rather than by a reader of the result, and a stamp beside an
 * `ntfy_error` is that pattern in its natural habitat. So the projection
 * carries both, and the view shows them together rather than showing "sent".
 *
 * As in the Pulse projection, this is an ALLOW-LIST. Notification bodies can
 * quote command output, so they are truncated; `prev_hash`/`row_hash` from the
 * audit chain are carried because they are the evidence a row was not edited,
 * and they are not secrets.
 *
 * Pure — vitest runs it in node.
 */

export interface WingEventView {
	id: number;
	ts: string;
	type: string;
	runId: string | null;
	/** Free-text channel: callback / operator / agent:<name>. */
	source: string | null;
	actorId: string | null;
	/** Groups every event of one logical action. The thread key. */
	actorActionId: string | null;
	host: string | null;
	task: string | null;
	durationMs: number | null;
	changed: boolean | null;
	/** True when the row carries a chain hash, i.e. it is covered by the
	 *  tamper-evident audit chain rather than merely present. */
	chained: boolean;
}

export interface WingNotificationView {
	id: number;
	severity: string;
	title: string;
	body: string;
	actorId: string | null;
	actorActionId: string | null;
	originPlugin: string | null;
	channels: string[];
	read: boolean;
	/** A later message from the same emitter replaced this one (wing.db
	 *  `superseded_at`). NOT read — nobody read it — and not unread work. */
	superseded: boolean;
	/** Per-channel delivery, as claimed. `error` is what makes a stamp
	 *  meaningful — a dispatch time with an error beside it is not a delivery. */
	ntfyAt: string | null;
	ntfyError: string | null;
	mailAt: string | null;
	mailError: string | null;
}

export const BODY_LIMIT = 400;

interface RawEvent {
	id?: number;
	ts?: string;
	type?: string;
	run_id?: string | null;
	source?: string | null;
	actor_id?: string | null;
	actor_action_id?: string | null;
	host?: string | null;
	task?: string | null;
	duration_ms?: number | null;
	changed?: number | boolean | null;
	row_hash?: string | null;
}

interface RawNotification {
	id?: number;
	severity?: string;
	title?: string;
	body?: string;
	actor_id?: string | null;
	actor_action_id?: string | null;
	origin_plugin?: string | null;
	channels_json?: string | null;
	wing_inbox_read_at?: string | null;
	superseded_at?: string | null;
	ntfy_dispatched_at?: string | null;
	ntfy_error?: string | null;
	mail_dispatched_at?: string | null;
	mail_error?: string | null;
}

export function projectEvent(raw: RawEvent): WingEventView {
	return {
		id: Number(raw.id ?? 0),
		ts: String(raw.ts ?? ''),
		type: String(raw.type ?? ''),
		runId: raw.run_id ?? null,
		source: raw.source ?? null,
		actorId: raw.actor_id ?? null,
		actorActionId: raw.actor_action_id ?? null,
		host: raw.host ?? null,
		task: raw.task ?? null,
		durationMs: raw.duration_ms ?? null,
		changed: raw.changed === null || raw.changed === undefined ? null : Boolean(raw.changed),
		chained: Boolean(raw.row_hash)
	};
}

export function projectNotification(raw: RawNotification): WingNotificationView {
	let channels: string[] = [];
	try {
		const parsed = JSON.parse(raw.channels_json ?? '[]');
		if (Array.isArray(parsed)) channels = parsed.map(String);
	} catch {
		// A malformed channel list is not a reason to drop the notification —
		// it is a reason to show it with no channels, which reads as "nobody
		// was told", the honest answer.
		channels = [];
	}
	return {
		id: Number(raw.id ?? 0),
		severity: String(raw.severity ?? ''),
		title: String(raw.title ?? ''),
		body: String(raw.body ?? '').slice(0, BODY_LIMIT),
		actorId: raw.actor_id ?? null,
		actorActionId: raw.actor_action_id ?? null,
		originPlugin: raw.origin_plugin ?? null,
		channels,
		read: Boolean(raw.wing_inbox_read_at),
		superseded: Boolean(raw.superseded_at),
		ntfyAt: raw.ntfy_dispatched_at ?? null,
		ntfyError: raw.ntfy_error ?? null,
		mailAt: raw.mail_dispatched_at ?? null,
		mailError: raw.mail_error ?? null
	};
}

export interface WingSnapshot {
	events: WingEventView[];
	/** Total rows in the events table, from upstream — the events list is a
	 *  window onto it, and saying so stops "60 events" reading as "60 exist". */
	eventsTotal: number;
	notifications: WingNotificationView[];
	/** Notifications whose dispatch stamp sits beside a dispatch error. */
	contestedDeliveries: number;
}

/**
 * Unread WORK — what the menubar counts and the list highlights.
 *
 * MEASURED 2026-09-01: the menubar read `!read` alone, so it showed 7 alerts
 * where 6 were live — one CRITICAL had been retired by its own successor and
 * had no way to stop being unread. One predicate, both callers.
 */
export function isUnreadWork(n: WingNotificationView): boolean {
	return !n.read && !n.superseded;
}

/** True when a channel claims a delivery time AND records an error for it. */
export function isContested(n: WingNotificationView): boolean {
	return Boolean((n.ntfyAt && n.ntfyError) || (n.mailAt && n.mailError));
}

export function projectWing(eventsPayload: unknown, notifPayload: unknown): WingSnapshot {
	const ep = (eventsPayload ?? {}) as { items?: RawEvent[]; total?: number };
	const np = (notifPayload ?? {}) as { notifications?: RawNotification[] };
	const notifications = (np.notifications ?? []).map(projectNotification);
	return {
		events: (ep.items ?? []).map(projectEvent),
		eventsTotal: Number(ep.total ?? 0),
		notifications,
		contestedDeliveries: notifications.filter(isContested).length
	};
}
