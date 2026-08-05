import { describe, it, expect } from 'vitest';
import { chips, QUIET, type SystemStatus } from './status';

const s = (over: Partial<SystemStatus> = {}): SystemStatus => ({
	...QUIET,
	visible: true,
	...over
});

describe('the menubar shows nothing to a non-admin', () => {
	it('renders no chips at all when invisible', () => {
		// Not an error, not a placeholder. Operational internals are Tier-1
		// information, and a permanent error badge in every tier-3 user's
		// corner teaches everyone to ignore that corner.
		expect(chips({ ...QUIET, failing: 9 })).toEqual([]);
	});
});

describe('nothing wrong renders as nothing, never as ok', () => {
	it('produces no chips when every count is zero', () => {
		expect(chips(s())).toEqual([]);
	});

	it('has no chip whose tone is ok, in any state', () => {
		// A green tick in a menubar is a claim of health. This estate had a
		// container report healthy for ten days while serving its own
		// installer; the shell does not make that claim.
		const all = chips(s({ failing: 1, overdue: 1, never: 1, alerts: 1, contested: 1 }));
		expect(all.map((c) => c.tone)).not.toContain('ok');
	});
});

describe('ranking', () => {
	it('puts active failures before staleness', () => {
		const out = chips(s({ failing: 2, never: 5, overdue: 3 }));
		expect(out.map((c) => c.key)).toEqual(['failing', 'never', 'overdue']);
	});

	it('routes each chip to the view that answers it', () => {
		const out = chips(s({ failing: 1, alerts: 1, boneAlive: false }));
		const by = Object.fromEntries(out.map((c) => [c.key, c.view]));
		expect(by.failing).toBe('pulse');
		expect(by.alerts).toBe('wing');
		expect(by.bone).toBe('bone');
	});

	it('says Bone is down only when it was actually checked', () => {
		// null = not checked this cycle. Rendering that as "down" would be a
		// failure invented from an absent measurement.
		expect(chips(s({ boneAlive: null })).map((c) => c.key)).not.toContain('bone');
		expect(chips(s({ boneAlive: true })).map((c) => c.key)).not.toContain('bone');
		expect(chips(s({ boneAlive: false })).map((c) => c.key)).toContain('bone');
	});
});

describe('an unbuildable summary is its own state', () => {
	it('replaces every chip with one that says so', () => {
		// The counts are meaningless if the summary failed to build; showing
		// "0 failing" beside an error would be the calm-absence defect again.
		const out = chips(s({ error: 'Wing did not answer', failing: 0, never: 0 }));
		expect(out).toHaveLength(1);
		expect(out[0].key).toBe('error');
		expect(out[0].tone).toBe('bad');
		expect(out[0].title).toContain('Nothing below was checked');
	});
});

describe('every chip explains itself', () => {
	it('carries a title long enough to be a sentence', () => {
		// The chip is two words in a menubar; the tooltip is where an operator
		// learns what it means without opening anything.
		for (const c of chips(s({ failing: 1, overdue: 1, never: 1, alerts: 1, contested: 1 }))) {
			expect(c.title.length, `${c.key} has no explanation`).toBeGreaterThan(30);
		}
	});
});
