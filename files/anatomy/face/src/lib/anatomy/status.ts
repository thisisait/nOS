/**
 * The menubar's system pulse — one compact summary, derived server-side.
 *
 * WHY IT EXISTS. The operator's stated need is "naprostý přehled o tom, co se
 * se systémem děje" — total awareness of what the system is doing. The Anatomy
 * app answers that, but only while it is open. A desktop's menubar is the one
 * surface that is ALWAYS visible, and until now it held a wordmark and a
 * username: the shell could not tell you a scheduled job had been failing for
 * three days unless you went looking.
 *
 * WHY ONE ENDPOINT AND NOT THREE. The menubar polls forever, on every session.
 * Three calls a minute per user to build one line is a cost the answer does not
 * justify, and it puts the reduction in the browser where three partial
 * failures have to be reconciled. `/bff/status` does it once, server-side.
 *
 * WHAT IT DELIBERATELY DOES NOT DO. It never renders "all good". A green tick
 * in a menubar is a claim, and this estate has been burned by exactly that
 * claim — a container reported healthy for ten days while serving its own
 * installer. When there is nothing wrong, the indicator is QUIET: a neutral
 * dot, no count. Silence means "nothing to report"; it does not mean "verified
 * fine", and it should not look like it does.
 *
 * Pure — vitest runs it in node.
 */
import type { Tone } from '$lib/components/ui';

export interface SystemStatus {
	/** False for non-admins: the menubar shows nothing at all rather than an
	 *  error. Operational internals are Tier-1 information. */
	visible: boolean;
	/** Scheduled jobs whose last run failed. */
	failing: number;
	/** Jobs past their scheduled fire time beyond the grace window. */
	overdue: number;
	/** Registered jobs that have never fired once. */
	never: number;
	/** Unread wing-inbox notifications at high/critical severity. */
	alerts: number;
	/** Notifications that claim a dispatch AND record an error for it. */
	contested: number;
	/** Bone answered its liveness probe. `null` = not checked this cycle. */
	boneAlive: boolean | null;
	/** Set when the summary itself could not be built. Distinct from zeroes. */
	error?: string;
}

export const QUIET: SystemStatus = {
	visible: false,
	failing: 0,
	overdue: 0,
	never: 0,
	alerts: 0,
	contested: 0,
	boneAlive: null
};

/** One badge in the menubar. */
export interface StatusChip {
	key: string;
	label: string;
	count?: number;
	tone: Tone;
	/** Which Anatomy view answers this chip when clicked. */
	view: 'pulse' | 'wing' | 'bone';
	title: string;
}

/**
 * The chips to render, worst first. An empty array means "nothing to report",
 * and the caller renders a quiet dot rather than inventing a positive.
 *
 * `never` is included even though it is not an incident: a job registered and
 * never fired is the single most invisible failure this estate has, and nine of
 * twenty-five jobs were in that state when it was first measured. It is ranked
 * below active failures and above staleness.
 */
export function chips(s: SystemStatus): StatusChip[] {
	if (!s.visible) return [];
	const out: StatusChip[] = [];
	if (s.error) {
		out.push({
			key: 'error',
			label: 'status unavailable',
			tone: 'bad',
			view: 'pulse',
			title: `The status summary could not be built: ${s.error}. Nothing below was checked.`
		});
		return out;
	}
	if (s.failing > 0)
		out.push({
			key: 'failing',
			label: 'failing',
			count: s.failing,
			tone: 'bad',
			view: 'pulse',
			title: `${s.failing} scheduled job(s) whose last run reported a non-zero exit`
		});
	if (s.alerts > 0)
		out.push({
			key: 'alerts',
			label: 'unread',
			count: s.alerts,
			tone: 'bad',
			view: 'wing',
			title: `${s.alerts} unread high/critical notification(s)`
		});
	if (s.contested > 0)
		out.push({
			key: 'contested',
			label: 'undelivered',
			count: s.contested,
			tone: 'bad',
			view: 'wing',
			title: `${s.contested} notification(s) stamped as dispatched with an error recorded beside the stamp`
		});
	if (s.never > 0)
		out.push({
			key: 'never',
			label: 'never ran',
			count: s.never,
			tone: 'warn',
			view: 'pulse',
			title: `${s.never} registered job(s) that have never fired once`
		});
	if (s.overdue > 0)
		out.push({
			key: 'overdue',
			label: 'overdue',
			count: s.overdue,
			tone: 'warn',
			view: 'pulse',
			title: `${s.overdue} job(s) past their scheduled fire time — a whole column of these means the Pulse daemon is not firing`
		});
	if (s.boneAlive === false)
		out.push({
			key: 'bone',
			label: 'Bone down',
			tone: 'bad',
			view: 'bone',
			title: 'Bone did not answer its liveness probe'
		});
	return out;
}

/**
 * The single dot shown when there are no chips.
 *
 * NEUTRAL, never ok — see the module header. The tooltip says what was and was
 * not established, because "quiet" is a much weaker claim than "healthy" and
 * the difference is the whole reason this shell exists.
 */
export function quietTone(s: SystemStatus): Tone {
	return s.visible && !s.error ? 'neutral' : 'neutral';
}
