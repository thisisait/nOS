/**
 * Pulse projection — the Anatomy view's data contract, and the place where the
 * upstream response STOPS.
 *
 * ── WHY THIS IS A PROJECTION AND NOT A PROXY ────────────────────────────────
 *
 * Measured on this estate, 2026-08-05: `GET /api/v1/pulse_jobs` returns each
 * job's `env_json` verbatim, and across 23 of the 25 registered jobs that is 57
 * live credential values — `WING_EVENTS_HMAC_SECRET` (Bone's event-signing key)
 * fifteen times, `WING_API_TOKEN` eleven, `NOS_AGENT_CLIENT_SECRET` ten, plus
 * KEAP agent tokens, `NOS_MARIADB_ROOT_PASSWORD` and `MAIL_PASSWORD`. Anything
 * forwarded to the browser is readable in devtools by everyone who can open the
 * app, and is cached wherever the response is cached.
 *
 * So this module maps upstream rows onto an EXPLICIT allow-list. Adding a field
 * is a deliberate edit here, not a consequence of upstream adding one — which
 * is the property that matters: a new secret-bearing column upstream cannot
 * arrive in a browser by default.
 *
 * ── WHY THE STATES ARE SHAPED THIS WAY ──────────────────────────────────────
 *
 * This view exists because of the 2026-08-04 Uptime Kuma finding: a container
 * that reported healthy to Docker and 200 on every route for ten days while
 * serving its own installer. Every signal the operator owned was green. So the
 * rule the states encode is that ABSENCE MUST NEVER RENDER AS CALM:
 *
 *   never    — the job has no run at all. Nine of twenty-five jobs are in this
 *              state right now, and nothing in the estate said so before this.
 *   failing  — its last run reported a non-zero exit.
 *   overdue  — `next_fire_at` is in the past beyond a grace window. This is the
 *              signal that catches a DEAD DAEMON: Wing only advances
 *              next_fire_at when a run finishes, so a Pulse that stopped firing
 *              leaves every job's scheduled time frozen in the past.
 *   running  — claimed, no finish recorded yet.
 *   ok       — ran, finished, exit 0, not late.
 *
 * `paused` is a FLAG, not a state: it is an operator decision that coexists
 * with any of the above, and a paused job cannot be "overdue" because nothing
 * is scheduling it. Conflating the two would let a deliberate pause hide a job
 * that has also never run.
 *
 * Pure — no server imports, no fetch — so vitest runs it in node.
 */

/** One job as the browser is allowed to see it. */
export interface PulseJobView {
	id: string;
	plugin: string;
	job: string;
	runner: string;
	schedule: string;
	/** Basename of the command only. The full path is host layout, and the args
	 *  and env blocks are withheld entirely — see the module header. */
	commandName: string;
	/** Env variable NAMES the job is handed. Wing redacts the values at the
	 *  source (PulsePresenter::withoutSecrets); the names are the useful half —
	 *  "this job holds a Wing API token" is what an operator auditing the
	 *  catalog needs — and a name is not a credential. */
	envKeys: string[];
	paused: boolean;
	pausedReason: string | null;
	nextFireAt: string | null;
	lastFiredAt: string | null;
	state: PulseState;
	category: string | null;
	/** Seconds past `next_fire_at`, when overdue; null otherwise. */
	overdueBySeconds: number | null;
	lastExitCode: number | null;
	lastFinishedAt: string | null;
	lastDurationMs: number | null;
	/** Truncated stderr of the last run, when it failed. Empty otherwise. */
	lastError: string;
	runsWindow: number;
	failsWindow: number;
	consecutiveFailures: number;
	/** True when no summary row exists upstream, i.e. the job has never run. */
	neverRan: boolean;
}

export type PulseState = 'never' | 'failing' | 'overdue' | 'running' | 'findings' | 'ok';

/** Fields upstream sends that must NEVER reach a browser. Named rather than
 *  implied, so the test can assert against the same list the code refuses. */
export const WITHHELD_UPSTREAM_FIELDS = ['env_json', 'args_json', 'command'] as const;

/** Longest stderr excerpt carried to the browser. Enough to read the reason of
 *  a failure without a click — the operator's stated need — and short enough
 *  that a job dumping its environment on crash does not dump all of it. */
export const ERROR_TAIL_LIMIT = 600;

/**
 * Grace before a job counts as overdue. Jitter is added to `next_fire_at`
 * upstream, and the daemon polls on an interval, so a job is legitimately a few
 * minutes late; flagging that would train the operator to ignore the flag.
 */
export function graceSeconds(jitterMin: number): number {
	return Math.max(15 * 60, jitterMin * 60 * 2);
}

interface RawJob {
	id?: string;
	plugin_name?: string;
	job_name?: string;
	runner?: string;
	schedule?: string;
	command?: string;
	env_keys?: string[];
	jitter_min?: number | string;
	paused?: number | boolean;
	paused_reason?: string | null;
	next_fire_at?: string | null;
	last_fired_at?: string | null;
	/** Exit codes the job declares as "ran correctly, found something". */
	findings_exit_codes?: number[] | null;
	/** Purpose group. Absent on any Wing older than 2026-08-06, which is why
	 *  the projection defaults it to null rather than to a bucket name. */
	category?: string | null;
}

interface RawSummary {
	last_exit_code?: number | null;
	last_finished_at?: string | null;
	last_duration_ms?: number | null;
	last_stderr_tail?: string | null;
	runs_window?: number;
	fails_window?: number;
	consecutive_failures?: number;
}

const num = (v: unknown, fallback = 0): number =>
	typeof v === 'number' && Number.isFinite(v) ? v : Number(v) || fallback;

/** `/a/b/run-drift.sh` → `run-drift.sh`; a bare name passes through. */
function basename(command: string): string {
	const parts = command.split('/').filter(Boolean);
	return parts.length ? parts[parts.length - 1] : '';
}

function parseTime(v: string | null | undefined): number | null {
	if (!v) return null;
	const t = Date.parse(v);
	return Number.isNaN(t) ? null : t;
}

/**
 * Project one job + its summary into the view model.
 *
 * `summary` is `undefined` when the job has never run — the upstream shape
 * encodes "never ran" as ABSENCE on purpose, so that a job with no history
 * cannot be mistaken for one with a clean history.
 */
export function projectJob(
	raw: RawJob,
	summary: RawSummary | undefined,
	now: number
): PulseJobView {
	const paused = raw.paused === 1 || raw.paused === true;
	const neverRan = summary === undefined || !raw.last_fired_at;
	const exit = summary?.last_exit_code ?? null;
	const finished = summary?.last_finished_at ?? null;

	// Exit codes this job DECLARES as "ran correctly, found something".
	// gitleaks and discovery both exit 1 for that, and reading it as failure is
	// how a night that carried news looked identical to a broken scanner.
	// Declared per job because the codes disagree between tools.
	const findingsCodes = Array.isArray(raw.findings_exit_codes)
		? raw.findings_exit_codes.map(Number).filter((c: number) => Number.isFinite(c) && c !== 0)
		: [];
	const hasFindings = exit !== null && findingsCodes.includes(exit);

	const nextAt = parseTime(raw.next_fire_at);
	const jitter = num(raw.jitter_min);
	let overdueBy: number | null = null;
	// A paused job is not late — nothing is scheduling it. Computing overdue
	// for it would turn a deliberate operator decision into a false alarm.
	if (!paused && nextAt !== null) {
		const late = Math.floor((now - nextAt) / 1000) - graceSeconds(jitter);
		if (late > 0) overdueBy = Math.floor((now - nextAt) / 1000);
	}

	// `findings` sits between ok and failing on purpose. It is NOT a health
	// state — the job worked — but rendering it as plain `ok` would bury the
	// one result an operator has to act on, and rendering it as `failing`
	// teaches them to ignore the channel. It is the presence counterpart to
	// this module's rule about absence.
	const failed = exit !== null && exit !== 0 && !hasFindings;

	let state: PulseState;
	if (neverRan) state = 'never';
	else if (failed) state = 'failing';
	else if (overdueBy !== null) state = 'overdue';
	else if (finished === null) state = 'running';
	else if (hasFindings) state = 'findings';
	else state = 'ok';
	return {
		id: String(raw.id ?? ''),
		plugin: String(raw.plugin_name ?? ''),
		job: String(raw.job_name ?? ''),
		runner: String(raw.runner ?? ''),
		schedule: String(raw.schedule ?? ''),
		commandName: basename(String(raw.command ?? '')),
		// Names only, and only ones upstream already redacted to names. If a
		// Wing that still sends `env_json` is ever on the other end, this is
		// empty rather than wrong — the projection does not parse the block.
		envKeys: Array.isArray(raw.env_keys) ? raw.env_keys.map(String) : [],
		paused,
		pausedReason: raw.paused_reason ?? null,
		nextFireAt: raw.next_fire_at ?? null,
		lastFiredAt: raw.last_fired_at ?? null,
		state,
		/** Purpose grouping, declared per job. `null` renders as its own
		 *  "uncategorised" group — never folded into another, because a job
		 *  nobody classified is a thing to notice. */
		category: raw.category ?? null,
		overdueBySeconds: overdueBy,
		lastExitCode: exit,
		lastFinishedAt: finished,
		lastDurationMs: summary?.last_duration_ms ?? null,
		lastError: failed ? String(summary?.last_stderr_tail ?? '').slice(0, ERROR_TAIL_LIMIT) : '',
		runsWindow: num(summary?.runs_window),
		failsWindow: num(summary?.fails_window),
		consecutiveFailures: num(summary?.consecutive_failures),
		neverRan
	};
}

/** What the view renders, plus the counts it leads with. */
export interface PulseSnapshot {
	generatedAt: string;
	windowHours: number;
	jobs: PulseJobView[];
	counts: Record<PulseState | 'paused' | 'total', number>;
}

/**
 * Project the two upstream payloads into one snapshot.
 *
 * `jobs` arrives from Wing as a MAP keyed by job id, not an array. Accepting
 * both shapes is not defensive politeness — a caller that assumed an array
 * would render an empty list against a healthy API, which is precisely the
 * failure this view exists to make impossible.
 */
export function projectSnapshot(
	jobsPayload: unknown,
	summaryPayload: unknown,
	now: number = Date.now()
): PulseSnapshot {
	const jp = (jobsPayload ?? {}) as { generated_at?: string; jobs?: unknown };
	const sp = (summaryPayload ?? {}) as {
		window_hours?: number;
		summaries?: Record<string, RawSummary>;
	};
	const rawJobs: RawJob[] = Array.isArray(jp.jobs)
		? (jp.jobs as RawJob[])
		: Object.values((jp.jobs ?? {}) as Record<string, RawJob>);
	const summaries = sp.summaries ?? {};

	const jobs = rawJobs
		.map((j) => projectJob(j, summaries[String(j.id ?? '')], now))
		.sort((a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state] || a.id.localeCompare(b.id));

	const counts: Record<string, number> = {
		never: 0,
		failing: 0,
		overdue: 0,
		running: 0,
		findings: 0,
		ok: 0,
		paused: 0,
		total: jobs.length
	};
	for (const j of jobs) {
		counts[j.state] += 1;
		if (j.paused) counts.paused += 1;
	}

	return {
		generatedAt: String(jp.generated_at ?? ''),
		windowHours: num(sp.window_hours, 24),
		jobs,
		counts: counts as PulseSnapshot['counts']
	};
}

/** Worst first. The operator should not have to scroll to find the problem. */
const STATE_ORDER: Record<PulseState, number> = {
	failing: 0,
	never: 1,
	overdue: 2,
	// Above `running` and `ok`: a scanner that found something outranks a job
	// that is merely busy. It is news, and news the operator has to read.
	findings: 3,
	running: 4,
	ok: 5
};
