/**
 * The Wing projection's job is to keep a CLAIM of delivery separate from a
 * delivery, and a windowed list separate from a total.
 */
import { describe, it, expect } from 'vitest';
import {
	projectEvent,
	projectNotification,
	projectWing,
	isContested,
	isUnreadWork,
	BODY_LIMIT
} from './wing';

describe('events', () => {
	it('reads the shape Wing actually sends', () => {
		// Field names copied from a live GET /api/v1/events response.
		const e = projectEvent({
			id: 111660,
			ts: '2026-08-05T02:13:52Z',
			run_id: 'scan_1785895261_59658',
			type: 'scan.batch_done',
			actor_id: null,
			actor_action_id: null,
			row_hash: 'ac31f23ede624c5b'
		});
		expect(e.type).toBe('scan.batch_done');
		expect(e.runId).toBe('scan_1785895261_59658');
		expect(e.chained).toBe(true);
	});

	it('marks a row with no chain hash as unchained', () => {
		// The audit chain is the evidence a row was not edited. A row outside
		// it is not proof of anything, and must not look like proof.
		expect(projectEvent({ id: 1, row_hash: null }).chained).toBe(false);
		expect(projectEvent({ id: 1 }).chained).toBe(false);
	});

	it('keeps `changed` tri-state', () => {
		// null means the event never reported it. Coercing that to false would
		// invent a claim that nothing changed.
		expect(projectEvent({ changed: 1 }).changed).toBe(true);
		expect(projectEvent({ changed: 0 }).changed).toBe(false);
		expect(projectEvent({}).changed).toBeNull();
	});
});

describe('notifications', () => {
	const base = {
		id: 38,
		severity: 'medium',
		title: 'S2 diff: 3 nights of agreement',
		body: 'Agreement holds over 45 real user document(s).',
		channels_json: '["wing-inbox"]'
	};

	it('parses the channel list', () => {
		expect(projectNotification(base).channels).toEqual(['wing-inbox']);
	});

	it('renders a malformed channel list as "nobody was told"', () => {
		// The honest reading. Dropping the notification would hide it; guessing
		// a channel would claim a delivery nobody made.
		expect(projectNotification({ ...base, channels_json: '{oops' }).channels).toEqual([]);
	});

	it('truncates the body', () => {
		const n = projectNotification({ ...base, body: 'x'.repeat(9000) });
		expect(n.body.length).toBe(BODY_LIMIT);
	});

	it('carries the dispatch stamp AND its error, never just the stamp', () => {
		const n = projectNotification({
			...base,
			ntfy_dispatched_at: '2026-08-05T06:00:00Z',
			ntfy_error: 'connection refused'
		});
		expect(n.ntfyAt).toBeTruthy();
		expect(n.ntfyError).toBe('connection refused');
		// The whole point: a time written by the SENDER is not a delivery.
		expect(isContested(n)).toBe(true);
	});

	it('does not call a clean dispatch contested', () => {
		const n = projectNotification({ ...base, mail_dispatched_at: '2026-08-05T06:00:00Z' });
		expect(isContested(n)).toBe(false);
	});

	it('a retired row is neither read nor unread work', () => {
		// MEASURED 2026-09-01: the menubar counted `!read` alone and showed 7
		// alerts where 6 were live — a CRITICAL its own successor had retired.
		const n = projectNotification({ ...base, superseded_at: '2026-08-31T01:02:03Z' });
		expect(n.superseded).toBe(true);
		expect(n.read).toBe(false); // nobody read it; the estate must not claim so
		expect(isUnreadWork(n)).toBe(false);
	});

	it('still counts a live unread row', () => {
		expect(isUnreadWork(projectNotification(base))).toBe(true);
		expect(
			isUnreadWork(projectNotification({ ...base, wing_inbox_read_at: '2026-08-31T09:00:00Z' }))
		).toBe(false);
	});

	it('does not call an error with no stamp contested', () => {
		// Nothing claimed success here, so there is no contradiction — just a
		// failure, which the row already shows.
		const n = projectNotification({ ...base, ntfy_error: 'boom' });
		expect(isContested(n)).toBe(false);
	});
});

describe('the snapshot', () => {
	it('keeps the window separate from the total', () => {
		// "60 events" must not read as "60 events exist" when the table holds
		// 111 660 of them.
		const s = projectWing({ items: [{ id: 1 }], total: 111660 }, { notifications: [] });
		expect(s.events).toHaveLength(1);
		expect(s.eventsTotal).toBe(111660);
	});

	it('counts contested deliveries across the inbox', () => {
		const s = projectWing(
			{ items: [], total: 0 },
			{
				notifications: [
					{ id: 1, ntfy_dispatched_at: 't', ntfy_error: 'e' },
					{ id: 2, mail_dispatched_at: 't', mail_error: 'e' },
					{ id: 3, ntfy_dispatched_at: 't' }
				]
			}
		);
		expect(s.contestedDeliveries).toBe(2);
	});

	it('an empty upstream is zeroes, not a crash', () => {
		const s = projectWing({}, {});
		expect(s.events).toEqual([]);
		expect(s.eventsTotal).toBe(0);
		expect(s.notifications).toEqual([]);
	});
});
