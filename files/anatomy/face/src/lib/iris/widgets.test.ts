// A widget's answer is routed by its token to that widget, never into the chat log; a refusal
// that names a widget is that widget's (wire.rs ToShell::Widget, Refused.widget; genui I5f).
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { ToShell } from './wire';
import { onTableChanged, route, submit, type Widgets } from './widgets';

const FIXTURE = new URL('../../../../contracts/thalamus-shell.fixture.json', import.meta.url);
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

// genui I5g: a form's submit is locked while in flight; a write re-runs the widgets that read its table.
describe('form submit and table changes', () => {
	const F = '5f0c1b2a-3d4e-4f5a-8b6c-7d8e9f0a1b2c';
	const formed = () => route({}, sample('a widget form'), 1)!;

	it('a submit sends once while it is in flight', () => {
		const one = submit(formed(), 'w4', { form: F, values: { amount: 42, kind: 'tools' } });
		expect(one.send).toEqual({ t: 'form_submit', form: F, widget: 'w4', values: { amount: 42, kind: 'tools' } });
		expect(one.w.w4.inFlight).toBe(true);
		const two = submit(one.w, 'w4', { form: F, values: { amount: 42, kind: 'tools' } });
		expect(two.send, 'a double click sends one message').toBeNull();
		expect(two.w).toBe(one.w);
	});

	it('form_result unlocks the form and says the row; a refusal unlocks it too', () => {
		const sent = submit(formed(), 'w4', { form: F, values: { amount: 42 } }).w;
		const done = route(sent, sample('a widget form added a row'), 5)!;
		expect(done.w4).toMatchObject({ inFlight: false, added: 'e3', at: 5, error: null });
		expect(done.w4.component?.kind, 'the form stays drawn for the next row').toBe('form');
		const bad = route(sent, { t: 'refused', reason: 'amount is required', widget: 'w4' }, 6)!;
		expect(bad.w4).toMatchObject({ inFlight: false, error: 'amount is required' });
	});

	it('a table change re-runs the active widgets that read it, marks the rest stale, never a form', () => {
		const w: Widgets = {
			rows: { component: null, error: null, at: 1, spec: { rows: { table: 'expenses' } } },
			chart: { component: null, error: null, at: 1, spec: { chart: { query: { table: 'expenses' }, chart: 'bar', x: 'kind', op: 'count' } } },
			away: { component: null, error: null, at: 1, spec: { rows: { table: 'expenses' } } },
			form: { component: null, error: null, at: 1, spec: { form: { table: 'expenses' } } },
			other: { component: null, error: null, at: 1, spec: { rows: { table: 'todos' } } },
			bare: { component: null, error: null, at: 1 },
		};
		const r = onTableChanged(w, 'expenses', ['rows', 'chart', 'form', 'other', 'bare']);
		expect(r.send).toEqual([
			{ t: 'widget', widget: 'rows', spec: { rows: { table: 'expenses' } }, trigger: 'table_changed' },
			{ t: 'widget', widget: 'chart', spec: { chart: { query: { table: 'expenses' }, chart: 'bar', x: 'kind', op: 'count' } }, trigger: 'table_changed' },
		]);
		expect(r.w.away.stale, 'off the active tab: stale, run when shown').toBe(true);
		expect([r.w.rows.stale, r.w.form.stale, r.w.other.stale]).toEqual([undefined, undefined, undefined]);
		const fresh = route(r.w, { t: 'widget', session: 's', widget: 'away', component: (sample("a widget's chart") as Extract<ToShell, { t: 'widget' }>).component }, 9)!;
		expect(fresh.away.stale, 'a new answer is not stale').toBe(false);
		expect(fresh.away.spec, 'the spec survives its answer').toEqual({ rows: { table: 'expenses' } });
	});

	it('a table change is not a widget message', () => {
		expect(route({}, sample('a write changed a table'), 1)).toBeNull();
	});
});
