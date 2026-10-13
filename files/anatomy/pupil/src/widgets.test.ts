// A widget's answer is routed by its token to that widget, never into the chat log; a refusal
// that names a widget is that widget's (wire.rs ToShell::Widget, Refused.widget; genui I5f).
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { ToShell } from './wire';
import { route } from './widgets';

const FIXTURE = new URL('../../contracts/thalamus-shell.fixture.json', import.meta.url);
const fx = JSON.parse(readFileSync(FIXTURE, 'utf8')) as { to_shell: { case: string; msg: ToShell }[] };
const sample = (name: string) => fx.to_shell.find((c) => c.case === name)!.msg;

describe('widget routing', () => {
	it('a widget message lands on its token, not the log', () => {
		const w = route({}, sample("a widget's chart"), 1000);
		expect(w).not.toBeNull();
		expect(Object.keys(w!)).toEqual(['w2']);
		expect(w!.w2).toMatchObject({ error: null, at: 1000 });
		expect(w!.w2.component?.kind).toBe('chart');
	});

	it('a refusal naming a widget lands on it and keeps its last answer', () => {
		const ok = route({}, sample("a widget's chart"), 1000)!;
		const bad = route(ok, sample('a refused widget names it'), 2000)!;
		expect(bad.w2.error).toContain('no column `kinds`');
		expect(bad.w2.component?.kind, 'the last answer stays drawn under the error').toBe('chart');
		expect(bad.w2.at).toBe(2000);
		const fresh = route(bad, sample("a widget's chart"), 3000)!;
		expect(fresh.w2.error, 'a new answer clears the error').toBeNull();
	});

	it('every other message is the log\'s, and other widgets are left alone', () => {
		for (const name of ['refusal', 'model text', 'a chart the model shows', 'a row edit awaits approval'])
			expect(route({}, sample(name), 1), name).toBeNull();
		const two = route(route({}, sample("a widget's chart"), 1)!, sample('a widget form'), 2)!;
		expect(Object.keys(two).sort()).toEqual(['w2', 'w4']);
		expect(two.w2.at).toBe(1);
	});

	it('routing does not mutate the state it was given', () => {
		const before = route({}, sample("a widget's chart"), 1)!;
		const snap = structuredClone(before);
		route(before, sample('a refused widget names it'), 2);
		expect(before).toEqual(snap);
	});
});
