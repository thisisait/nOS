/**
 * The Pulse projection's two jobs, tested separately because they fail
 * separately: it must not leak, and it must not let absence look like calm.
 *
 * The leak half is not hypothetical. Fixtures below carry the real field names
 * and value shapes measured from `GET /api/v1/pulse_jobs` on 2026-08-05, where
 * 23 of 25 jobs returned live credentials in `env_json`.
 */
import { describe, it, expect } from 'vitest';
import {
	projectJob,
	projectSnapshot,
	graceSeconds,
	ERROR_TAIL_LIMIT,
	WITHHELD_UPSTREAM_FIELDS
} from './pulse';

const NOW = Date.parse('2026-08-05T12:00:00Z');

/** Shaped exactly like a real row, secrets included. */
const rawJob = (over: Record<string, unknown> = {}) => ({
	id: 'conductor:security-drift-watch',
	plugin_name: 'conductor',
	job_name: 'security-drift-watch',
	runner: 'subprocess',
	command: '/Users/pazny/projects/nOS/files/anatomy/plugins/conductor/skills/drift-watch.sh',
	args_json: '[]',
	env_json: JSON.stringify({
		WING_EVENTS_HMAC_SECRET: '0c05d247e394026ab3240c7f11483ed61c426ca6048bc2c9eb6b156a1725c751',
		WING_API_TOKEN: 'wing_live_token_value_here_0123456789',
		NOS_MARIADB_ROOT_PASSWORD: 'hunter2hunter2hunter2'
	}),
	schedule: '0 6 * * *',
	jitter_min: 5,
	paused: 0,
	paused_reason: null,
	next_fire_at: '2026-08-06T06:03:00+00:00',
	last_fired_at: '2026-08-05T06:03:31+00:00',
	...over
});

const summary = (over: Record<string, unknown> = {}) => ({
	last_exit_code: 0,
	last_finished_at: '2026-08-05T06:04:01+00:00',
	last_duration_ms: 30_000,
	last_stderr_tail: '',
	runs_window: 1,
	fails_window: 0,
	consecutive_failures: 0,
	...over
});

describe('the projection does not leak', () => {
	it('carries no withheld field, under any name', () => {
		const view = projectJob(rawJob(), summary(), NOW);
		const keys = Object.keys(view);
		for (const withheld of WITHHELD_UPSTREAM_FIELDS) {
			expect(keys).not.toContain(withheld);
		}
	});

	it('carries no secret VALUE, which is the property that actually matters', () => {
		// A key-name check alone would pass a projection that copied the values
		// under a different name. Serialise the whole view and look for the
		// secrets themselves.
		const blob = JSON.stringify(projectJob(rawJob(), summary(), NOW));
		for (const secret of [
			'0c05d247e394026ab3240c7f11483ed61c426ca6048bc2c9eb6b156a1725c751',
			'wing_live_token_value_here_0123456789',
			'hunter2hunter2hunter2'
		]) {
			expect(blob).not.toContain(secret);
		}
	});

	it('publishes the command basename, not the host path', () => {
		const view = projectJob(rawJob(), summary(), NOW);
		expect(view.commandName).toBe('drift-watch.sh');
		expect(JSON.stringify(view)).not.toContain('/Users/pazny');
	});

	it('keeps env NAMES and never parses a value out of a legacy env_json', () => {
		// Wing redacts at the source now. A Wing that predates that change still
		// sends env_json; the projection must yield nothing from it rather than
		// helpfully reading it.
		const view = projectJob(rawJob({ env_keys: ['WING_API_TOKEN', 'FOO'] }), summary(), NOW);
		expect(view.envKeys).toEqual(['WING_API_TOKEN', 'FOO']);
		const legacy = projectJob(rawJob(), summary(), NOW);
		expect(legacy.envKeys).toEqual([]);
	});

	it('truncates the error tail', () => {
		const view = projectJob(
			rawJob(),
			summary({ last_exit_code: 1, last_stderr_tail: 'x'.repeat(5000) }),
			NOW
		);
		expect(view.lastError.length).toBe(ERROR_TAIL_LIMIT);
	});

	it('shows no error text at all for a job that did not fail', () => {
		const view = projectJob(rawJob(), summary({ last_stderr_tail: 'noisy but fine' }), NOW);
		expect(view.lastError).toBe('');
	});
});

describe('absence never renders as calm', () => {
	it('a job with no summary is `never`, not `ok`', () => {
		const view = projectJob(rawJob({ last_fired_at: null }), undefined, NOW);
		expect(view.state).toBe('never');
		expect(view.neverRan).toBe(true);
	});

	it('a paused job that never ran is still `never`', () => {
		// The regression this pins: treating `paused` as a state would let a
		// deliberate pause mask a job that has also never fired.
		const view = projectJob(
			rawJob({ paused: 1, paused_reason: 'manual:operator', last_fired_at: null }),
			undefined,
			NOW
		);
		expect(view.state).toBe('never');
		expect(view.paused).toBe(true);
	});

	it('a failed last run outranks everything else', () => {
		const view = projectJob(rawJob(), summary({ last_exit_code: 2 }), NOW);
		expect(view.state).toBe('failing');
		expect(view.lastExitCode).toBe(2);
	});

	it('flags a job whose next fire time is long past', () => {
		const view = projectJob(rawJob({ next_fire_at: '2026-08-01T06:00:00+00:00' }), summary(), NOW);
		expect(view.state).toBe('overdue');
		expect(view.overdueBySeconds).toBeGreaterThan(3 * 86400);
	});

	it('does not flag a job that is merely a little late', () => {
		// Jitter and the poll interval make small lateness normal. Flagging it
		// would train the operator to ignore the flag.
		const late = new Date(NOW - (graceSeconds(5) - 60) * 1000).toISOString();
		const view = projectJob(rawJob({ next_fire_at: late }), summary(), NOW);
		expect(view.state).toBe('ok');
	});

	it('never calls a paused job overdue — nothing is scheduling it', () => {
		const view = projectJob(
			rawJob({ paused: 1, next_fire_at: '2026-07-01T06:00:00+00:00' }),
			summary(),
			NOW
		);
		expect(view.overdueBySeconds).toBeNull();
		expect(view.state).toBe('ok');
	});

	it('an unfinished run is `running`, not a success', () => {
		const view = projectJob(rawJob(), summary({ last_finished_at: null }), NOW);
		expect(view.state).toBe('running');
	});
});

describe('the snapshot', () => {
	it('reads `jobs` as the MAP Wing actually sends', () => {
		// Wing returns {jobs: {id: {...}}}. A projection that assumed an array
		// would render an empty list against a perfectly healthy API — the
		// exact failure this whole view exists to make impossible.
		const snap = projectSnapshot(
			{ generated_at: 'now', jobs: { 'conductor:security-drift-watch': rawJob() } },
			{ window_hours: 24, summaries: { 'conductor:security-drift-watch': summary() } },
			NOW
		);
		expect(snap.jobs).toHaveLength(1);
		expect(snap.counts.total).toBe(1);
	});

	it('still works if upstream ever switches to an array', () => {
		const snap = projectSnapshot({ jobs: [rawJob()] }, { summaries: {} }, NOW);
		expect(snap.jobs).toHaveLength(1);
	});

	it('sorts worst first, so the first screenful holds every problem', () => {
		const snap = projectSnapshot(
			{
				jobs: {
					a: rawJob({ id: 'a' }),
					b: rawJob({ id: 'b', last_fired_at: null }),
					c: rawJob({ id: 'c' })
				}
			},
			{ summaries: { a: summary(), c: summary({ last_exit_code: 1 }) } },
			NOW
		);
		expect(snap.jobs.map((j) => j.state)).toEqual(['failing', 'never', 'ok']);
	});

	it('counts a paused job in both its state and the paused tally', () => {
		const snap = projectSnapshot(
			{ jobs: { a: rawJob({ id: 'a', paused: 1 }) } },
			{ summaries: { a: summary() } },
			NOW
		);
		expect(snap.counts.paused).toBe(1);
		expect(snap.counts.ok).toBe(1);
	});

	it('an empty upstream is zero jobs, not a crash', () => {
		const snap = projectSnapshot({}, {}, NOW);
		expect(snap.jobs).toEqual([]);
		expect(snap.counts.total).toBe(0);
	});
});
