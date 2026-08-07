import { describe, expect, it } from 'vitest';
import { ring, tally, arcs, arcPath, verdictRing, headroom, type Spoke } from './rings';

const spoke = (id: string, state: Spoke['state'], reason?: string): Spoke => ({
	id,
	label: id,
	state,
	reason
});

describe('ring invariants', () => {
	it('drives the arc count from the RECORDED denominator, not the row count', () => {
		// The contradiction scan's real shape: 125 compared, 25 with rows.
		const r = ring('pairs', 125, [spoke('a', 'good'), spoke('b', 'bad')]);
		expect(r).not.toBeNull();
		expect(r!.declared).toBe(125);
		expect(r!.unaccounted).toBe(123);
		expect(arcs(r!)).toHaveLength(125);
		// The gap renders as null-spoke arcs — visible, not normalised away.
		expect(arcs(r!).filter((a) => a.spoke === null)).toHaveLength(123);
	});

	it('refuses an empty ring — a level with nothing on it is a claim', () => {
		expect(ring('nothing', 0, [])).toBeNull();
	});

	it('refuses an unjudged spoke with no reason', () => {
		expect(() => ring('r', 1, [spoke('x', 'unjudged')])).toThrow(/reason/);
	});

	it('handles both measured extremes as the same component', () => {
		const five = ring('full', 5, Array.from({ length: 5 }, (_, i) => spoke(`j${i}`, 'good')));
		const many = ring(
			'pairs',
			125,
			Array.from({ length: 125 }, (_, i) => spoke(`p${i}`, i < 25 ? 'good' : 'unjudged', 'skip'))
		);
		expect(arcs(five!)).toHaveLength(5);
		expect(arcs(many!)).toHaveLength(125);
	});
});

describe('tally', () => {
	it('keeps unjudged separate from both verdicts', () => {
		const r = ring('r', 4, [
			spoke('a', 'good'),
			spoke('b', 'bad'),
			spoke('c', 'unjudged', 'container absent')
		])!;
		const t = tally(r);
		expect(t).toEqual({ good: 1, bad: 1, unjudged: 1, unaccounted: 1, declared: 4 });
	});
});

describe('arcPath', () => {
	it('emits a closed SVG path', () => {
		const d = arcPath(0, 0, 10, 20, 0, Math.PI / 2);
		expect(d.startsWith('M ')).toBe(true);
		expect(d.endsWith('Z')).toBe(true);
	});
});

describe('verdictRing', () => {
	const runs = [
		{
			uuid: 'r1',
			proposal_id: null,
			gate_set: 'fast',
			judge_name: 'ansible-lint',
			status: 'exited',
			outcome: 'pass',
			work_count: 1483,
			min_work: 1450,
			reason: null,
			started_at: 't'
		},
		{
			uuid: 'r2',
			proposal_id: null,
			gate_set: 'fast',
			judge_name: 'pytest-anatomy',
			status: 'skipped',
			outcome: 'indeterminate',
			work_count: null,
			min_work: 2900,
			reason: 'binary missing from PATH',
			started_at: 't'
		}
	];
	const verdict = {
		uuid: 'v1',
		proposal_id: null,
		gate_set: 'fast',
		result: 'indeterminate',
		evidence: JSON.stringify({ judge_runs: ['r1', 'r2'] }),
		created_at: 't'
	};

	it('declares the COMMITTED membership as denominator', () => {
		// The gate set declares 3 judges; only 2 rows exist. The third is
		// unaccounted — the recorded scope wins over the row count.
		const r = verdictRing(verdict, runs, ['ansible-lint', 'pytest-anatomy', 'genome-codegen']);
		expect(r!.declared).toBe(3);
		expect(r!.unaccounted).toBe(1);
		const t = tally(r!);
		expect(t.good).toBe(1);
		expect(t.unjudged).toBe(1); // INDETERMINATE is not bad and not good
	});

	it('an INDETERMINATE spoke carries the actionable reason', () => {
		const r = verdictRing(verdict, runs, ['ansible-lint', 'pytest-anatomy']);
		const skipped = r!.spokes.find((s) => s.id === 'r2')!;
		expect(skipped.state).toBe('unjudged');
		expect(skipped.reason).toContain('binary missing');
	});

	it('survives malformed evidence without inventing spokes', () => {
		const r = verdictRing({ ...verdict, evidence: 'not-json' }, runs, ['a', 'b']);
		expect(r!.spokes).toHaveLength(0);
		expect(r!.unaccounted).toBe(2);
	});
});

describe('headroom — the ratchet as a proportion', () => {
	it('calls a pass sitting just above its floor tight', () => {
		// 2026-08-07 reality: 3014 tests against a floor of 2980.
		const h = headroom(3014, 2980);
		expect(h.pct).toBe(1);
		expect(h.tight).toBe(true);
	});

	it('does not call a comfortable pass tight', () => {
		// The 12x gap the estate shipped with: floor 200 against 2456 executed.
		const h = headroom(2456, 200);
		expect(h.tight).toBe(false);
		expect(h.pct).toBeGreaterThan(1000);
	});

	it('puts the fill short of the tick when the run did less work', () => {
		// The shape the bar exists to show: work below its own floor.
		const h = headroom(2731, 2874);
		expect(h.pct).toBeLessThan(0);
		expect(h.fillPct).toBeLessThan(h.tickPct);
		expect(h.tight).toBe(true);
	});

	it('keeps the tick in a fixed place so judges are comparable', () => {
		// 2 artifacts, 1489 files and 3014 tests must land the tick in the same
		// place, or the eye cannot compare two rows of one list.
		const ticks = [headroom(2, 2), headroom(1489, 1450), headroom(3014, 2980)].map((h) =>
			Math.round(h.tickPct)
		);
		expect(new Set(ticks).size).toBe(1);
	});

	it('clamps a run far above its floor instead of overflowing the row', () => {
		expect(headroom(100_000, 10).fillPct).toBe(100);
	});

	it('refuses to divide by a floor of zero', () => {
		// min_work is nullable upstream; a judge with no ratchet must render as
		// nothing, never as a bar claiming 100%.
		const h = headroom(500, 0);
		expect(h.fillPct).toBe(0);
		expect(h.tight).toBe(false);
	});
});
