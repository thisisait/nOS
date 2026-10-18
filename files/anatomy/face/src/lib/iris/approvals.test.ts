// The approval queue holds the terminal shell's invariants (thalamus/src/shell.rs):
// oldest first, one shown (30-32); approve only once the whole edit was shown (33, 175,
// 221-223), reject at any time (176); one decision each (179); closed = not decided (157-161).
// Gate: tests/anatomy/test_pupil_approvals_hold.py.
import { readFileSync } from 'node:fs';
import { compile } from 'svelte/compiler';
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import ApprovalCard from './ApprovalCard.svelte';
import { asked, closed, composerOpen, decide, empty, seen } from './approvals';
import type { ToShell } from './wire';

const FIXTURE = new URL('../../../../contracts/thalamus-shell.fixture.json', import.meta.url);
const fx = JSON.parse(readFileSync(FIXTURE, 'utf8')) as { to_shell: { msg: ToShell }[] };
const req = fx.to_shell.map((c) => c.msg).find((m) => m.t === 'approval_request') as Extract<ToShell, { t: 'approval_request' }>;
const two = asked(asked(empty(), req), { ...req, approval: 'second' });

describe('the approval queue', () => {
	it('approve before the end of the edit was in view sends nothing', () => {
		const r = decide(two, req.approval, 'approve');
		expect(r.send).toBeNull();
		expect(r.q.pending.map((w) => w.approval)).toEqual([req.approval, 'second']);
	});

	it('approve after the end was in view sends one decision for the oldest', () => {
		const r = decide(seen(two, req.approval), req.approval, 'approve');
		expect(r.send).toEqual({ t: 'approval_decision', approval: req.approval, decision: 'approve', note: null });
		expect(r.q.pending.map((w) => w.approval)).toEqual(['second']);
	});

	it('a second decision on the same id sends nothing', () => {
		const once = decide(seen(two, req.approval), req.approval, 'approve');
		expect(decide(once.q, req.approval, 'approve').send).toBeNull();
		expect(decide(once.q, req.approval, 'reject').send).toBeNull();
	});

	it('reject needs no scroll', () => {
		expect(decide(two, req.approval, 'reject').send?.t).toBe('approval_decision');
	});

	it('only the oldest is decided, and seeing a later one unlocks nothing', () => {
		expect(decide(two, 'second', 'reject').send).toBeNull();
		expect(decide(seen(two, 'second'), req.approval, 'approve').send).toBeNull();
	});

	it('the next approval needs its own end in view', () => {
		const next = decide(seen(two, req.approval), req.approval, 'reject').q;
		expect(decide(next, 'second', 'approve').send).toBeNull();
	});

	it('the composer is shut while any approval waits', () => {
		expect(composerOpen(empty())).toBe(true);
		expect(composerOpen(two)).toBe(false);
	});

	it('a closed link leaves every pending one not decided, and the queue empty', () => {
		const r = closed(seen(two, req.approval));
		expect(r.notes).toEqual([`not decided, nothing written: approval ${req.approval}`, 'not decided, nothing written: approval second']);
		expect(r.q.pending).toEqual([]);
		expect(decide(r.q, req.approval, 'approve').send).toBeNull();
	});
});

describe('the approval card', () => {
	const draw = (whole: boolean) =>
		render(ApprovalCard, { props: { waiting: two.pending[0], of: 2, whole, ondecide: () => {}, onseen: () => {} } }).body;

	it('says 1 of N and keeps Approve disabled until the end was in view', () => {
		const html = draw(false);
		expect(html).toContain('1 of 2');
		expect(html).toMatch(/<button[^>]*disabled[^>]*>approve<\/button>/);
		expect(html).not.toMatch(/<button[^>]*disabled[^>]*>reject<\/button>/);
		expect(draw(true)).not.toMatch(/<button[^>]*disabled[^>]*>approve<\/button>/);
	});
});

describe('the diff list', () => {
	// A value with no break point must wrap, not hide behind a side scroll the end
	// marker cannot see: the GUI form of shell.rs wrap (no part of a value cut off).
	it('wraps every value inside the card', () => {
		const src = readFileSync(new URL('./Component.svelte', import.meta.url), 'utf8');
		const css = compile(src, { filename: 'Component.svelte', css: 'external' }).css?.code ?? '';
		const rule = [...css.matchAll(/([^{}]+)\{([^}]*)\}/g)].find(([, sel]) => /\.diff[^,]*\bli\b/.test(sel));
		expect(rule?.[2]).toMatch(/overflow-wrap:\s*anywhere/);
		expect(rule?.[2]).toMatch(/white-space:\s*pre-wrap/);
	});
});
