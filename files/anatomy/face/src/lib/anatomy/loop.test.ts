import { describe, expect, it } from 'vitest';
import { projectLoop, WITHHELD_LOOP_FIELDS } from './loop';

describe('projectLoop', () => {
	it('maps onto the allow-list and drops everything else', () => {
		const snap = projectLoop(
			{
				proposals: [
					{
						id: 1,
						uuid: 'u1',
						weakness_id: 'w',
						intent_class: 'config-fix',
						gate_set: 'fast',
						attempt_n: 2,
						created_at: 't',
						// A regressed upstream sending the artifact anyway:
						diff_text: 'SECRET HUNK',
						fingerprint: 'fp'
					}
				]
			},
			{ judge_runs: [{ uuid: 'r', gate_set: 'fast', judge_name: 'j', status: 'exited', sandbox_path: '/host/layout' }] },
			{ verdicts: [{ uuid: 'v', gate_set: 'fast', result: 'pass', evidence: '{}', created_at: 't' }] }
		);
		for (const field of WITHHELD_LOOP_FIELDS) {
			expect(JSON.stringify(snap)).not.toContain(field);
		}
		expect(JSON.stringify(snap)).not.toContain('SECRET HUNK');
		expect(JSON.stringify(snap)).not.toContain('/host/layout');
		expect(snap.proposals[0].uuid).toBe('u1');
		expect(snap.counts).toEqual({ proposals: 1, judgeRuns: 1, verdicts: 1 });
	});

	it('treats absent payloads as empty lists, never as a crash', () => {
		const snap = projectLoop(undefined, null, {});
		expect(snap.counts).toEqual({ proposals: 0, judgeRuns: 0, verdicts: 0 });
	});
});
