/** Anatomy → Pulse client. Read-only: there is no write helper here because
 *  the BFF exports no write handler. Actions live in Wing UI, where the tier
 *  gates already are. */
import { bffGet } from './client';
import type { PulseSnapshot } from '$lib/anatomy/pulse';

/** The snapshot, plus the two ways it can be unavailable. `configured: false`
 *  means the token is not wired; `error` means Wing answered badly. Neither is
 *  an empty job list, and the view must not render them as one. */
export type PulseResponse = Partial<PulseSnapshot> & {
	configured: boolean;
	note?: string;
	error?: string;
};

export async function loadPulse(): Promise<PulseResponse> {
	return bffGet<PulseResponse>('/bff/pulse');
}

/** One run as Wing stores it — the detail pane shows these verbatim. */
export interface PulseRunRow {
	run_id: string;
	job_id: string;
	fired_at: string;
	finished_at: string | null;
	exit_code: number | null;
	duration_ms: number | null;
	stdout_tail: string | null;
	stderr_tail: string | null;
	actor_id: string | null;
	actor_action_id: string | null;
}

export async function loadRuns(
	jobId: string
): Promise<{ runs: PulseRunRow[]; error?: string }> {
	const r = await bffGet<{ runs?: PulseRunRow[]; error?: string }>('/bff/pulse', {
		job_id: jobId
	});
	return { runs: r.runs ?? [], error: r.error };
}
