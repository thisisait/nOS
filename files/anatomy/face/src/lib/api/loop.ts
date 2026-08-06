/** Anatomy → Runs client. The ledger reads plus the screen's ONE write —
 *  running a declared gate set by name. The BFF refuses everything else
 *  (see /bff/loop/judge for the enumerated refusals the UI renders). */
import { bffGet, bffPost } from './client';
import type { LoopSnapshot } from '$lib/anatomy/loop';

export type LoopResponse = Partial<LoopSnapshot> & {
	configured: boolean;
	note?: string;
	error?: string;
};

export async function loadLoop(): Promise<LoopResponse> {
	return bffGet<LoopResponse>('/bff/loop');
}

/** 202 + job id. Body is exactly {gate_set}; anything else is a 400. */
export async function runGateSet(gateSet: string): Promise<unknown> {
	return bffPost<unknown>('/bff/loop/judge', { gate_set: gateSet });
}

export async function judgeStatus(jobId: string): Promise<unknown> {
	return bffGet<unknown>('/bff/loop/judge', { job_id: jobId });
}
