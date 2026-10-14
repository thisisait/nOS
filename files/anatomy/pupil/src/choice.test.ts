// A choice Iris asks at a fork (renderers.rs Choice): native radios, or checkboxes when multi,
// the suggestion preselected and marked "navrženo", every label a text node; "Odpovědět" sends
// choice_reply once, with exactly the picked labels. Nothing is sent without that click.
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Choice from './Choice.svelte';
import Message from './Message.svelte';
import { initial, reply, toggle } from './choice';
import type { ChoiceProps, ToShell } from './wire';

const S = '0b6f6a1e-3c2d-4e5f-8a9b-0c1d2e3f4a5b';
const C = '3c9e1d2f-4a5b-4c6d-8e7f-9a0b1c2d3e4f';
const one: ChoiceProps = {
	id: C, question: 'Which table should I chart first?', multi: false, suggested: ['todos'],
	options: [{ label: 'todos', note: 'the open work' }, { label: 'expenses' }, { label: '<b>both</b>' }],
};
const many: ChoiceProps = { ...one, multi: true, suggested: ['todos', 'expenses'] };
const html = (choice: ChoiceProps, onreply?: (m: unknown) => void) => render(Choice, { props: { choice, session: S, onreply } }).body;
const text = (h: string) => h.replace(/<[^>]*>/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ');

describe('a choice is drawn as native inputs, every label as text', () => {
	it('the question, every label and note reach the page as text', () => {
		const h = html(one);
		for (const s of [one.question, 'todos', 'the open work', 'expenses', '<b>both</b>']) expect(text(h)).toContain(s);
		expect(h).not.toContain('<b>both</b>');
	});

	it('single is radios, multi is checkboxes; the suggestion is preselected and marked navrženo', () => {
		const radios = html(one).match(/<input[^>]*>/g) ?? [];
		expect(radios.length).toBe(3);
		expect(radios.every((i) => /type="radio"/.test(i))).toBe(true);
		expect(radios.filter((i) => /\bchecked\b/.test(i)).length).toBe(1);
		expect(radios[0]).toMatch(/\bchecked\b/);
		const boxes = html(many).match(/<input[^>]*>/g) ?? [];
		expect(boxes.every((i) => /type="checkbox"/.test(i))).toBe(true);
		expect(boxes.filter((i) => /\bchecked\b/.test(i)).length).toBe(2);
		expect(text(html(one)).match(/navrženo/g)?.length).toBe(1);
		expect(text(html(many)).match(/navrženo/g)?.length).toBe(2);
		expect(text(html(one))).toContain('Odpovědět');
	});

	it('drawing it sends nothing', () => {
		let sent = 0;
		html(one, () => sent++);
		render(Message, { props: { msg: { t: 'render', session: S, component: { kind: 'choice', props: one } }, onchoose: () => sent++ } });
		expect(sent).toBe(0);
	});
});

describe('the reply', () => {
	it('starts from the suggestion', () => {
		expect(initial(one)).toEqual(['todos']);
		expect(initial(many)).toEqual(['todos', 'expenses']);
	});

	it('single: a pick replaces the last one; multi: a pick toggles', () => {
		expect(toggle(one, ['todos'], 'expenses')).toEqual(['expenses']);
		expect(toggle(many, ['todos', 'expenses'], 'todos')).toEqual(['expenses']);
		expect(toggle(many, ['expenses'], '<b>both</b>')).toEqual(['expenses', '<b>both</b>']);
		expect(toggle(one, ['todos'], 'promotions')).toEqual(['todos']);
	});

	it('sends exactly the picked labels, in the order offered', () => {
		expect(reply(S, one, ['expenses'], false)).toEqual({ t: 'choice_reply', session: S, choice: C, picked: ['expenses'] });
		expect(reply(S, many, ['<b>both</b>', 'todos'], false)).toEqual({ t: 'choice_reply', session: S, choice: C, picked: ['todos', '<b>both</b>'] });
	});

	it('sends nothing twice, nothing empty, nothing not offered, never two on a single', () => {
		expect(reply(S, one, ['todos'], true)).toBeNull();
		expect(reply(S, many, [], false)).toBeNull();
		expect(reply(S, one, ['promotions'], false)).toBeNull();
		expect(reply(S, one, ['todos', 'expenses'], false)).toBeNull();
	});

	it('an answered choice says the answer and holds its inputs and button', () => {
		const h = render(Choice, { props: { choice: one, session: S, answered: ['expenses'] } }).body;
		expect(text(h)).toContain('odpověď: expenses');
		for (const el of h.match(/<(input|button)[^>]*>/g) ?? []) expect(el).toMatch(/\bdisabled\b/);
	});
});

describe('the message log routes a choice to its card', () => {
	it('a choice render draws the card, with no pin and no renderer gap', () => {
		const msg: ToShell = { t: 'render', session: S, component: { kind: 'choice', props: one } };
		const h = render(Message, { props: { msg } }).body;
		expect(h).not.toContain('no renderer for component kind');
		expect(text(h)).toContain('Odpovědět');
		expect(h).not.toContain('Připnout');
	});
});
