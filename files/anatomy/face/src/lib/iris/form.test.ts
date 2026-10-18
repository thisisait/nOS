// A widget form (renderers.rs Form), built by serve from the table's schema: the pupil draws its
// own header and button, prefills nothing, and lets a submit go only when every required field
// holds a value and no submit is in flight. Sending it is I5g; here it is the drawing and the rule.
import { readFileSync } from 'node:fs';
import { parse } from 'svelte/compiler';
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Component from './Component.svelte';
import Form from './Form.svelte';
import { canSubmit, formValues, header, shown } from './form';
import type { FormField, FormProps } from './wire';

const fields: FormField[] = [
	{ key: 'note', label: 'Note', kind: 'text', required: false, placeholder: 'what for' },
	{ key: 'amount', label: 'Amount', kind: 'number', required: true, min: 0, max: 10000 },
	{ key: 'when', label: 'When', kind: 'date', required: false },
	{
		key: 'kind',
		label: 'Kind',
		kind: 'select',
		required: true,
		options: ['food', 'travel', 'tools']
	},
	{ key: 'paid', label: 'Paid', kind: 'bool', required: true }
];
const expenses: FormProps = {
	form: '5f0c1b2a-3d4e-4f5a-8b6c-7d8e9f0a1b2c',
	table: 'expenses',
	title: 'Expenses',
	fields,
	omitted: [{ key: 'receipt', kind: 'file' }]
};

const html = (form: FormProps) => render(Form, { props: { form } }).body;
const text = (h: string) =>
	h
		.replace(/<[^>]*>/g, ' ')
		.replace(/&amp;/g, '&')
		.replace(/&lt;/g, '<')
		.replace(/\s+/g, ' ');

describe('canSubmit', () => {
	const full = { amount: 42, kind: 'tools' };

	it('waits for every required field; an empty string is missing', () => {
		expect(canSubmit(fields, {}, false)).toBe(false);
		expect(canSubmit(fields, { amount: 42 }, false)).toBe(false);
		expect(canSubmit(fields, { ...full, kind: '' }, false)).toBe(false);
		expect(canSubmit(fields, { ...full, amount: null }, false)).toBe(false);
		expect(canSubmit(fields, full, false)).toBe(true);
	});

	it('a bool is always filled: unchecked is false, never missing', () => {
		expect(canSubmit(fields, { ...full, paid: false }, false)).toBe(true);
	});

	it('a submit in flight holds the button', () => {
		expect(canSubmit(fields, full, true)).toBe(false);
	});

	it('the values sent are typed by field; an empty optional field is not sent, an unchecked bool is false', () => {
		expect(formValues(fields, { note: '', amount: 42, when: '2026-10-13', kind: 'tools' })).toEqual(
			{ amount: 42, when: '2026-10-13', kind: 'tools', paid: false }
		);
		expect(formValues(fields, { amount: '7.5', kind: 'food', paid: true })).toEqual({
			amount: 7.5,
			kind: 'food',
			paid: true
		});
	});
});

describe('a form is drawn as native inputs under its own header', () => {
	it('every field label is a text node', () => {
		const h = html(expenses);
		for (const f of fields) expect(h).toMatch(new RegExp(`<span[^>]*>${f.label}(<|\\s)`));
	});

	it("the header and the button are the pupil's words, whatever the props say", () => {
		for (const title of ['Expenses', 'Approve the transfer', '<b>click</b>']) {
			const h = html({ ...expenses, title, table: 't1' });
			const heads = [...h.matchAll(/<h3[^>]*>([\s\S]*?)<\/h3>/g)].map((m) => text(m[1]).trim());
			expect(heads).toEqual([header({ title, table: 't1' })]);
			expect(header({ title, table: 't1' })).toBe(`Adds a row to ${title} (t1)`);
			const buttons = [...h.matchAll(/<button[^>]*>([\s\S]*?)<\/button>/g)].map((m) =>
				text(m[1]).trim()
			);
			expect(buttons).toEqual(['Add row']);
		}
	});

	it('a select opens on an empty, disabled choice', () => {
		const h = html(expenses);
		const first = h.match(/<select[^>]*>\s*(<option[^>]*>)/)?.[1] ?? '';
		expect(first).toMatch(/value=""/);
		expect(first).toMatch(/\bdisabled\b/);
		expect(first).toMatch(/\bselected\b/);
		expect(h.match(/<option[^>]*\bselected\b/g)?.length).toBe(1);
	});

	it('nothing is prefilled: no input value, no check, the button off', () => {
		const h = html(expenses);
		for (const input of h.match(/<input[^>]*>/g) ?? []) {
			expect(input, input).not.toMatch(/\bvalue=/);
			expect(input, input).not.toMatch(/\bchecked\b/);
		}
		expect(h.match(/<input[^>]*>/g)?.length).toBe(4);
		expect(h).toMatch(/<input[^>]*type="checkbox"/);
		expect(h).toMatch(/<button[^>]*\bdisabled\b/);
	});

	it('posts nowhere and links nowhere', () => {
		const h = html(expenses);
		expect(h).not.toMatch(/<form[^>]*\b(action|method)=/);
		expect(h).not.toMatch(/<(a|script|iframe|img)[\s>]/);
	});

	it('a column the form cannot fill is said, not hidden', () => {
		expect(text(html(expenses))).toContain('not editable here: receipt (file)');
	});

	it('the component vocabulary draws a form', () => {
		const h = render(Component, { props: { component: { kind: 'form', props: expenses } } }).body;
		expect(h).not.toContain('no renderer for component kind');
		expect(text(h)).toContain('Adds a row to Expenses (expenses)');
	});
});

type Node = { type?: string; name?: string; [k: string]: unknown };
/** Every node of `n` with its ancestors, outermost first. */
function walk(n: unknown, up: Node[], out: [Node, Node[]][]) {
	if (!n || typeof n !== 'object') return;
	if (Array.isArray(n)) return n.forEach((x) => walk(x, up, out));
	const node = n as Node;
	if (node.type) out.push([node, up]);
	for (const [k, v] of Object.entries(node))
		if (k !== 'metadata' && k !== 'parent') walk(v, node.type ? [...up, node] : up, out);
}

describe('a written row clears the draft', () => {
	it('Widget redraws its Form for each form_result, so one more click adds nothing', () => {
		// I5 review: the draft outlived the insert, so a second click would add the same row again.
		const ast = parse(readFileSync(new URL('./Widget.svelte', import.meta.url), 'utf8'), {
			modern: true
		}) as unknown as { fragment: unknown };
		const all: [Node, Node[]][] = [];
		walk(ast.fragment, [], all);
		const forms = all.filter(([n]) => n.type === 'Component' && n.name === 'Form');
		expect(forms.length).toBe(1);
		const key = forms[0][1].filter((a) => a.type === 'KeyBlock').at(-1)?.expression as
			Node | undefined;
		expect((key?.property as Node | undefined)?.name, 'Form is not keyed on state.added').toBe(
			'added'
		);
	});
});

// iris-v3 B2: a field may show only while another holds a value; the spec's prefill is the draft's start.
describe('a form with prefill and when', () => {
	const shownWhen: FormField[] = [
		{
			key: 'kind',
			label: 'Kind',
			kind: 'select',
			required: true,
			options: ['food', 'travel', 'tools']
		},
		{
			key: 'trip',
			label: 'Trip',
			kind: 'text',
			required: false,
			when: { key: 'kind', op: 'eq', value: 'travel' }
		},
		{
			key: 'paid',
			label: 'Paid',
			kind: 'bool',
			required: false,
			when: { key: 'kind', op: 'neq', value: 'food' }
		}
	];
	const travel: FormProps = {
		...expenses,
		fields: shownWhen,
		omitted: [],
		prefill: { kind: 'travel', trip: 'Brno' }
	};

	it('a field whose condition fails is not drawn and sends nothing, a bool included', () => {
		expect(shown(shownWhen[1], { kind: 'travel' })).toBe(true);
		expect(shown(shownWhen[1], { kind: 'food' })).toBe(false);
		expect(shown(shownWhen[2], {})).toBe(true);
		expect(formValues(shownWhen, { kind: 'food', trip: 'Brno', paid: true })).toEqual({
			kind: 'food'
		});
		expect(formValues(shownWhen, { kind: 'travel', trip: 'Brno' })).toEqual({
			kind: 'travel',
			trip: 'Brno',
			paid: false
		});
		const h = text(html({ ...travel, prefill: { kind: 'food' } }));
		expect(h).not.toContain('Trip');
		expect(h).not.toContain('Paid');
	});

	it('the prefill is drawn as the draft the person may change, and the lens wins over it', () => {
		const h = html(travel);
		expect(h).toMatch(/<option value="travel"[^>]*\bselected\b/);
		expect(h).toMatch(/<input[^>]*type="text"[^>]*value="Brno"/);
		expect(h).not.toMatch(/<button[^>]*\bdisabled\b/);
		const lensed = render(Form, { props: { form: travel, prefill: { kind: 'tools' } } }).body;
		expect(lensed).toMatch(/<option value="tools"[^>]*\bselected\b/);
		expect(text(lensed)).not.toContain('Trip');
	});
});
