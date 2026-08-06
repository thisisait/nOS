/** Anatomy → Pulse client. Reads, plus exactly ONE write: §4b run-now
 *  (2026-08-06), which RUNS something already declared and can alter nothing
 *  — body allow-list {job_id}, no env/command override exists on the path,
 *  and the daemon remains the only executor. Every other action stays in
 *  Wing UI, where the tier gates already are. */
import { bffGet, bffPost } from './client';
import type { PulseSnapshot } from '$lib/anatomy/pulse';
import type { WingSnapshot } from '$lib/anatomy/wing';
import type { BoneSnapshot } from '$lib/anatomy/bone';

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
	jobId: string,
	since?: string,
	until?: string
): Promise<{ runs: PulseRunRow[]; error?: string }> {
	const params: Record<string, string> = { job_id: jobId };
	if (since) params.since = since;
	if (until) params.until = until;
	const r = await bffGet<{ runs?: PulseRunRow[]; error?: string }>('/bff/pulse', params);
	return { runs: r.runs ?? [], error: r.error };
}

/** §4b run-now. 202 = the REQUEST was recorded; the run itself appears in the
 *  runs feed when the daemon dispatches it — watch that, not this response. */
export async function runJobNow(jobId: string): Promise<{
	job_id?: string;
	next_fire_at?: string;
	actor_action_id?: string;
	note?: string;
}> {
	return bffPost('/bff/pulse/run', { job_id: jobId });
}

// ── Wing + Bone (the other two Anatomy views) ────────────────────────────────

export type WingResponse = Partial<WingSnapshot> & {
	configured: boolean;
	thread?: string;
	note?: string;
	error?: string;
};

/** `thread` is an `actor_action_id` — the value a Pulse run and the events it
 *  produced share. Passing it is what makes the three views one story. */
export async function loadWing(thread = '', type = ''): Promise<WingResponse> {
	const params: Record<string, string> = {};
	if (thread) params.thread = thread;
	if (type) params.type = type;
	return bffGet<WingResponse>('/bff/wing', params);
}

export type BoneResponse = Partial<BoneSnapshot> & { configured: boolean };

export async function loadBone(): Promise<BoneResponse> {
	return bffGet<BoneResponse>('/bff/bone');
}
