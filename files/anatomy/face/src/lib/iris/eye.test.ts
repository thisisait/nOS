// @vitest-environment happy-dom
// The eye shows what the thalamus says it is doing (wire `activity`), plus one local
// input — the person typing — labelled as local. Pure reducer; timers are `settle`.
// Gate: tests/anatomy/test_pupil_eye_reads_the_wire.py.
import { mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import Eye from './Eye.svelte';
// Imported, not read: under happy-dom import.meta.url is not a file URL.
import src from './Eye.svelte?raw';
import { SETTLE_MS, eye, look, mood, step, type Eye as EyeT, type Input, type View } from './eye';
import type { Phase, ToShell } from './wire';

const S = '0b6f6a1e-3c2d-4e5f-8a9b-0c1d2e3f4a5b';
const act = (phase: Phase): Input => ({ e: 'wire', msg: { t: 'activity', session: S, phase } });
const wire = (msg: ToShell): Input => ({ e: 'wire', msg });
const run = (...ins: Input[]) => ins.reduce(step, step(eye(), { e: 'link', state: 'connected' }));
const settle = (x: EyeT) => step(x, { e: 'settle', seq: x.seq });
const says = (v: View) => [mood(v).icon, mood(v).text];

describe('the eye reducer', () => {
	it('starts disconnected and opens to idle on link.connected', () => {
		expect(eye().state).toBe('disconnected');
		expect(run().state).toBe('idle');
	});

	it('follows the wire: thinking, tool:<name>, writing, idle', () => {
		expect(run(act('thinking')).state).toBe('thinking');
		const t = run(act({ tool: { name: 'query_rows' } }));
		expect([t.state, t.tool, mood(look(t, 0)).text]).toEqual([
			'tool',
			'query_rows',
			'using query_rows'
		]);
		expect(run(act('writing')).state).toBe('writing');
		expect(run(act('thinking'), act('idle')).state).toBe('idle');
	});

	it('refused returns to the previous non-error state after it settles', () => {
		const r = run(act('thinking'), wire({ t: 'refused', reason: 'x' }));
		expect(r.state).toBe('refused');
		expect(settle(r).state).toBe('thinking');
		// A second refusal keeps the first one's way back; a refusal from idle returns to idle.
		const twice = step(r, wire({ t: 'refused', reason: 'y' }));
		expect(settle(twice).state).toBe('thinking');
		expect(settle(run(wire({ t: 'refused', reason: 'x' }))).state).toBe('idle');
	});

	it('activity during a refusal is where it settles to, after the flicker', () => {
		const r = run(act('thinking'), wire({ t: 'refused', reason: 'x' }), act('idle'));
		expect(r.state).toBe('refused');
		expect(settle(r).state).toBe('idle');
	});

	it('said flashes, then idle; the turn-end idle does not cut the flash', () => {
		const s = run(act('thinking'), wire({ t: 'text', session: S, text: 'hi' }), act('idle'));
		expect(s.state).toBe('said');
		expect(settle(s).state).toBe('idle');
		expect(run(wire({ t: 'text', session: S, text: 'hi' }), act('thinking')).state).toBe(
			'thinking'
		);
	});

	it('a stale timer settles nothing', () => {
		const r = run(wire({ t: 'refused', reason: 'x' }));
		const stale = r.seq;
		const again = step(r, wire({ t: 'text', session: S, text: 'hi' }));
		expect(step(again, { e: 'settle', seq: stale }).state).toBe('said');
		expect(SETTLE_MS).toEqual({ said: 600, refused: 1500 });
	});

	it('waiting wins over everything until pending is 0', () => {
		for (const x of [
			run(),
			run(act('thinking')),
			run(act('writing')),
			run(wire({ t: 'refused', reason: 'x' }))
		])
			expect(look(x, 1)).toMatchObject({ state: 'waiting' });
		expect(look(run(act('thinking')), 0).state).toBe('thinking');
	});

	it('an open choice waits for the person like an approval does', () => {
		const x = run(act('idle'));
		expect(look(x, 0, 1)).toEqual({ state: 'waiting', tool: 'choice' });
		expect(mood(look(x, 0, 1)).text).toBe('your turn: answer');
		expect(mood(look(x, 1, 1)).text).toBe('your turn: approve');
		expect(look(x, 0, 0).state).toBe('idle');
	});

	it('disconnected on link.closed, over waiting, and deaf to the wire until connected', () => {
		const c = step(run(act('thinking')), { e: 'link', state: 'closed' });
		expect(look(c, 2).state).toBe('disconnected');
		expect(step(c, act('thinking')).state).toBe('disconnected');
		expect(step(c, { e: 'link', state: 'connected' }).state).toBe('idle');
	});

	it('typing is the one local input: listening, labelled local; sending assumes nothing', () => {
		const l = run({ e: 'typing', text: 'find' });
		expect(l.state).toBe('listening');
		expect(mood(look(l, 0)).text).toContain('local');
		expect(step(l, { e: 'typing', text: '' }).state).toBe('idle');
		// No activity yet after send: still listening, not a guessed "thinking".
		expect(
			step(l, wire({ t: 'session', session: S, actor: 'user:pazny', model_uri: 'm' })).state
		).toBe('listening');
		expect(step(l, act('thinking')).state).toBe('thinking');
		// Typing never overrides what the wire says.
		expect(step(run(act('thinking')), { e: 'typing', text: 'x' }).state).toBe('thinking');
	});
});

describe('the bubble beside the eye says the mood', () => {
	it('one turn, with the model awake, asleep and unknown', () => {
		const idle = { true: ['🫡', 'ready'], false: ['💤', 'model asleep'], null: ['', 'ready'] };
		for (const loaded of [true, false, null]) {
			let x = run({ e: 'model', loaded });
			expect([x.loaded, says(look(x, 0))]).toEqual([loaded, idle[`${loaded}`]]);
			x = step(x, { e: 'typing', text: 'find' });
			expect(says(look(x, 0))).toEqual(['👂', 'listening (local)']);
			x = step(x, act('thinking'));
			expect(says(look(x, 0))).toEqual(['🧠', 'thinking']);
			x = step(x, act({ tool: { name: 'query_rows' } }));
			expect(says(look(x, 0))).toEqual(['⛏️', 'using query_rows']);
			expect(says(look(x, 1))).toEqual(['✋', 'your turn: approve']);
			expect(says(look(x, 0, 1))).toEqual(['✋', 'your turn: answer']);
			x = step(x, act('writing'));
			expect(says(look(x, 0))).toEqual(['✍️', 'writing']);
			x = step(step(x, wire({ t: 'text', session: S, text: 'hi' })), act('idle'));
			expect(says(look(x, 0))).toEqual(['💬', 'said']);
			x = settle(x);
			expect(says(look(x, 0))).toEqual(idle[`${loaded}`]);
			x = step(x, wire({ t: 'refused', reason: 'x' }));
			expect(says(look(x, 0))).toEqual(['⚠️', 'refused']);
			x = step(settle(x), { e: 'link', state: 'closed' });
			expect(says(look(x, 1))).toEqual(['⛓️', 'offline']);
			// The model state survives the link: it is the thalamus's, not the socket's.
			x = step(step(x, { e: 'model', loaded: true }), { e: 'link', state: 'connected' });
			expect(says(look(x, 0))).toEqual(idle.true);
		}
		expect(says({ state: 'tool', tool: null })).toEqual(['⛏️', 'working']);
	});
});

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
	if (app) unmount(app);
	app = null;
	document.body.replaceChildren();
});
const draw = (view: View) => {
	if (app) unmount(app);
	app = mount(Eye, { target: document.body, props: { view } });
	return document.body;
};

describe('the eye drawn', () => {
	it('the bubble sits beside the eye, says the mood, and is a polite live region', () => {
		const b = draw({ state: 'thinking', tool: null, loaded: true });
		const eyeBox = b.querySelector('.eye')!;
		const [lens, bubble] = [...eyeBox.children];
		expect(lens.tagName.toLowerCase()).toBe('svg');
		expect(bubble.className).toContain('bubble');
		expect(bubble.getAttribute('data-mood')).toBe('thinking');
		expect(bubble.getAttribute('aria-live')).toBe('polite');
		expect(bubble.textContent).toContain('🧠');
		expect(bubble.textContent).toContain('thinking');
	});

	const views: View[] = [
		{ state: 'idle', tool: null },
		{ state: 'listening', tool: null },
		{ state: 'thinking', tool: null },
		{ state: 'tool', tool: 'query_rows' },
		{ state: 'writing', tool: null },
		{ state: 'waiting', tool: null },
		{ state: 'said', tool: null },
		{ state: 'refused', tool: null },
		{ state: 'disconnected', tool: null }
	];

	for (const v of views)
		it(`${v.state}: the mood text is always rendered and is the accessible name`, () => {
			const b = draw(v);
			expect(b.querySelector(`[data-state="${v.state}"]`)).not.toBeNull();
			expect(b.querySelector('[role="status"]')?.textContent).toContain(mood(v).text);
		});

	it('a tool name is text, never markup', () => {
		expect(draw({ state: 'tool', tool: '<img src=x>' }).querySelector('img')).toBeNull();
	});

	it('reduced motion stops every keyframe; colour and the label still say the state', () => {
		const reduced =
			src.match(/@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\t\}/)?.[1] ?? '';
		expect(reduced).toMatch(/animation: none/);
		expect(src).not.toMatch(/<canvas|getContext\(|@rive-app|<img/); // code, not the comment's prose
	});
});
