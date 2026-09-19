import { describe, it, expect } from 'vitest';
import {
	SERE_LOOP_ID,
	countForSereNode,
	ledgerOverlayApplies,
	pulseJobForLoop,
	pulseJobIdForLoop
} from './loop-overlay';
import type { LoopResponse } from '$lib/api/loop';
import type { PulseJobView } from './pulse';

const sereLive: LoopResponse = {
	configured: true,
	counts: { proposals: 9, judgeRuns: 19, verdicts: 4 },
	proposals: [
		{
			intent_class: 'patch',
			id: 1,
			uuid: 'x',
			weakness_id: 'rem:REM-1',
			gate_set: 'repo',
			attempt_n: 1,
			created_at: ''
		}
	],
	judgeRuns: [],
	verdicts: [
		{ uuid: 'v', proposal_id: 1, gate_set: 'repo', result: 'pass', evidence: '', created_at: '' }
	]
};

const scoutJob = {
	id: 'loop:news-scout',
	plugin: 'loop',
	job: 'news-scout',
	state: 'ok',
	neverRan: false
} as PulseJobView;

describe('loop overlay joins the selected loop', () => {
	it('applies the ledger only to sere', () => {
		expect(ledgerOverlayApplies(SERE_LOOP_ID)).toBe(true);
		expect(ledgerOverlayApplies('news-scout')).toBe(false);
		expect(ledgerOverlayApplies('repo-check')).toBe(false);
	});

	it('does not paint SERE counts onto news-scout', () => {
		expect(countForSereNode('table:loop_verdicts', 'news-scout', sereLive)).toBeNull();
		expect(countForSereNode('stage:propose', 'news-scout', sereLive)).toBeNull();
		expect(countForSereNode('intent:patch', 'news-scout', sereLive)).toBeNull();
	});

	it('still counts SERE nodes when SERE is selected', () => {
		expect(countForSereNode('table:loop_verdicts', 'sere', sereLive)).toBe(4);
		expect(countForSereNode('stage:propose', 'sere', sereLive)).toBe(9);
		expect(countForSereNode('intent:patch', 'sere', sereLive)).toBe(1);
	});

	it('maps an operational loop to its generated pulse id', () => {
		expect(pulseJobIdForLoop('news-scout')).toBe('loop:news-scout');
		expect(pulseJobForLoop('news-scout', [scoutJob])?.state).toBe('ok');
		expect(pulseJobForLoop('sere', [scoutJob])).toBeNull();
		expect(pulseJobForLoop('repo-check', [scoutJob])).toBeNull();
	});
});
