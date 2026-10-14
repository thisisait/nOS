// A choice Iris asks at a fork (renderers.rs Choice): native radios, or checkboxes when multi,
// the suggestion preselected and marked "navrženo", every label a text node; "Odpovědět" sends
// choice_reply once, with exactly the picked labels. Nothing is sent without that click.
import { readFileSync } from 'node:fs';
import { parse } from 'svelte/compiler';
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Choice from './Choice.svelte';
import Message from './Message.svelte';
import { answer, initial, reply, toggle } from './choice';
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

	it('the card is answered only once the reply was accepted; a refused one can be sent again', async () => {
		const m = reply(S, one, ['expenses'], false);
		if (m?.t !== 'choice_reply') throw new Error('no reply');
		expect(await answer(m, async () => true)).toEqual(['expenses']);
		expect(await answer(m, async () => false)).toBeNull();
		expect(await answer(m, async () => { throw new Error('an approval is waiting: decide it first'); })).toBeNull();
		expect(await answer(m)).toBeNull();
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

// SSR runs no effect, so 'drawing it sends nothing' above cannot see one; this reads the AST.
type Node = { type?: string; name?: string; [k: string]: unknown };
function walk(n: unknown, up: Node[], out: [Node, Node[]][]) {
	if (!n || typeof n !== 'object') return;
	if (Array.isArray(n)) return n.forEach((x) => walk(x, up, out));
	const node = n as Node;
	if (node.type) out.push([node, up]);
	for (const [k, v] of Object.entries(node)) if (k !== 'metadata' && k !== 'parent') walk(v, node.type ? [...up, node] : up, out);
}
const nodes = (file: string) => {
	const all: [Node, Node[]][] = [];
	walk(parse(readFileSync(new URL(file, import.meta.url), 'utf8'), { modern: true }), [], all);
	return all;
};
const declares = (name: string) => (a: Node) => a.type === 'VariableDeclarator' && (a.id as Node).name === name;
const isProps = (a: Node) => a.type === 'VariableDeclarator' && ((a.init as Node)?.callee as Node)?.name === '$props';
const uses = (all: [Node, Node[]][], name: string) => all.filter(([n, up]) => n.type === 'Identifier' && n.name === name && up.at(-1)?.id !== n);

describe('nothing is sent without the click', () => {
	it.each(['Choice.svelte', 'Message.svelte'])('%s runs no effect and no mount hook', (f) => {
		const hooks = nodes(f).filter(([n]) => n.type === 'Identifier' && ['$effect', 'onMount', 'beforeUpdate', 'afterUpdate'].includes(n.name ?? ''));
		expect(hooks.map(([n]) => n.name)).toEqual([]);
	});

	it('Choice: send is called only by the button click, and onreply only inside send', () => {
		const all = nodes('Choice.svelte');
		const sends = uses(all, 'send');
		expect(sends.length).toBe(1);
		for (const [, up] of sends) {
			const at = up.findIndex((a) => a.type === 'Attribute' && a.name === 'onclick');
			expect(at > 0 && up[at - 1].type === 'RegularElement' && up[at - 1].name === 'button', 'send outside a button onclick').toBe(true);
		}
		const replies = uses(all, 'onreply');
		expect(replies.some(([, up]) => up.some(declares('send')))).toBe(true);
		for (const [, up] of replies) expect(up.some(declares('send')) || up.some(isProps), 'onreply outside send').toBe(true);
	});

	it('Message: onchoose only reaches the Choice card as its onreply', () => {
		const all = uses(nodes('Message.svelte'), 'onchoose');
		expect(all.some(([, up]) => up.some((a) => a.type === 'Component' && a.name === 'Choice'))).toBe(true);
		for (const [, up] of all) {
			const at = up.findIndex((a) => a.type === 'Attribute' && a.name === 'onreply');
			expect(up.some(isProps) || (at > 0 && up[at - 1].type === 'Component' && up[at - 1].name === 'Choice'), 'onchoose outside Choice').toBe(true);
		}
	});
});
