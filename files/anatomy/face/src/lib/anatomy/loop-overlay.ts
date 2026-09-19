/**
 * Which live overlay a Loops view selection may wear.
 *
 * SERE has a ledger (proposals / judge runs / verdicts). A .loop.yml loop
 * has pulse_runs under id `loop:<id>`. Painting SERE pass/fail onto
 * news-scout is the other loop reading as this one.
 */
import type { LoopResponse } from '$lib/api/loop';
import type { PulseJobView } from './pulse';

export const SERE_LOOP_ID = 'sere';

export function pulseJobIdForLoop(loopId: string): string {
	return `loop:${loopId}`;
}

export function ledgerOverlayApplies(selectedLoop: string): boolean {
	return selectedLoop === SERE_LOOP_ID;
}

/** Live count for a SERE harness node, or null when this selection has none. */
export function countForSereNode(
	id: string,
	selectedLoop: string,
	live: LoopResponse | null
): number | null {
	if (!ledgerOverlayApplies(selectedLoop) || !live?.configured) return null;
	const c = live.counts;
	switch (id) {
		case 'stage:propose':
		case 'table:loop_proposals':
			return c?.proposals ?? 0;
		case 'stage:judge':
		case 'table:loop_judge_runs':
			return c?.judgeRuns ?? 0;
		case 'stage:apply':
		case 'table:loop_verdicts':
			return c?.verdicts ?? 0;
	}
	if (id.startsWith('intent:')) {
		const m = new Map<string, number>();
		for (const p of live.proposals ?? []) {
			m.set(p.intent_class, (m.get(p.intent_class) ?? 0) + 1);
		}
		return m.get(id.slice('intent:'.length)) ?? 0;
	}
	return null;
}

export function pulseJobForLoop(
	selectedLoop: string,
	jobs: PulseJobView[] | undefined
): PulseJobView | null {
	if (ledgerOverlayApplies(selectedLoop) || !jobs) return null;
	const id = pulseJobIdForLoop(selectedLoop);
	return jobs.find((j) => j.id === id) ?? null;
}
