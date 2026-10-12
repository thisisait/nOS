// Every to_shell sample of the contract fixture, rendered: each string the wire
// carried must reach the page as text (gate: tests/anatomy/test_pupil_renders_the_fixture.py).
import { readFileSync } from 'node:fs';
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Message from './Message.svelte';
import type { Component, ToShell, Value } from './wire';

const FIXTURE = new URL('../../contracts/thalamus-shell.fixture.json', import.meta.url);
const fx = JSON.parse(readFileSync(FIXTURE, 'utf8')) as { to_shell: { case: string; msg: ToShell }[] };
const KINDS = ['table_results', 'row_diff_approval', 'inbox_list', 'approvals_list', 'red_status'];

const text = (html: string) =>
	html
		.replace(/<[^>]*>/g, ' ')
		.replace(/&lt;/g, '<')
		.replace(/&gt;/g, '>')
		.replace(/&quot;/g, '"')
		.replace(/&#39;/g, "'")
		.replace(/&amp;/g, '&')
		.replace(/\s+/g, ' ');

const draw = (msg: ToShell) => text(render(Message, { props: { msg } }).body);

/** The strings and counts a renderer owes the person; table cells outside `columns` are not shown (as shell.rs). */
function owed(v: Value | Component, skip: Set<string> = new Set()): string[] {
	if (typeof v === 'string') return [v];
	// A zero count is said as words or left out ("nothing red"), as shell.rs does.
	if (typeof v === 'number') return v === 0 ? [] : [String(v)];
	if (Array.isArray(v)) return v.flatMap((x) => owed(x));
	if (v && typeof v === 'object')
		return Object.entries(v).flatMap(([k, x]) => (skip.has(k) ? [] : owed(x as Value)));
	return [];
}

function owedBy(c: Component): string[] {
	if (c.kind !== 'table_results') return owed(c.props as unknown as Value);
	const { table, columns, rows } = c.props;
	return [table, ...columns, ...rows.flatMap((r) => [r.__id, ...columns.flatMap((k) => owed(r.cells[k] ?? null))])];
}

describe('the pupil renders the contract fixture', () => {
	const components = fx.to_shell.flatMap((c) => ('component' in c.msg ? [c.msg.component] : []));

	it('the fixture holds every kind the pupil knows, and no other', () => {
		expect(new Set(components.map((c) => c.kind))).toEqual(new Set(KINDS));
	});

	for (const { case: name, msg } of fx.to_shell) {
		it(`draws "${name}" (${msg.t})`, () => {
			const page = draw(msg);
			expect(page).not.toContain('no renderer for component kind');
			// A chat line's session id is the banner's to show, not every line's.
			const skip = new Set(msg.t === 'session' ? ['t'] : ['t', 'session']);
			const want = 'component' in msg ? owedBy(msg.component) : owed(msg as unknown as Value, skip);
			for (const s of want) expect(page.toLowerCase(), `${name}: ${s}`).toContain(s.toLowerCase());
		});
	}

	it('says when a search was substring, and when it was semantic', () => {
		const msg = fx.to_shell.find((c) => 'component' in c.msg && c.msg.component.kind === 'table_results')!.msg;
		expect(draw(msg)).toContain('substring match, not semantic');
		const semantic = structuredClone(msg) as Extract<ToShell, { t: 'render' }>;
		(semantic.component.props as { projected: boolean }).projected = true;
		expect(draw(semantic)).not.toContain('substring');
		expect(draw(semantic)).toContain('semantic');
	});

	it('an empty diff side reads (empty), not blank', () => {
		const msg = fx.to_shell.find((c) => c.msg.t === 'approval_request')!.msg;
		expect(draw(msg)).toContain('(empty) → "landed"');
	});

	it('markup in a model string stays text', () => {
		const html = render(Message, { props: { msg: { t: 'text', session: 's', text: '<img src=x onerror=alert(1)>' } } }).body;
		expect(html).not.toContain('<img');
		expect(html).toContain('&lt;img');
	});
});
