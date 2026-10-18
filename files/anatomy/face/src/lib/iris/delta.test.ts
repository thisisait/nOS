// Change markers (iris-genui-change-markers): what an action would add, remove or change, as text
// (+ − ~) beside each item, a "+N −M ~K" row and a Před / Změny / Po switch. An added or removed
// parent passes its state to its children; renderers.rs check() refuses a child that says otherwise.
import { readFileSync } from 'node:fs';
import { parse } from 'svelte/compiler';
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Component from './Component.svelte';

const text = (html: string) =>
	html
		.replace(/<[^>]*>/g, ' ')
		.replace(/&gt;/g, '>')
		.replace(/&amp;/g, '&')
		.replace(/\s+/g, ' ')
		.trim();
const draw = (component: object, view?: string) => {
	const html = render(Component, {
		props: { component: component as never, ...(view ? { view: view as never } : {}) }
	}).body;
	return { html, text: text(html) };
};
/** Each <li>'s data-delta, in order, by its first label word. */
const marks = (html: string) =>
	[...html.matchAll(/<li([^>]*)>([\s\S]*?)(?=<li|<\/ul|<\/ol)/g)].map((m) => [
		text(m[2]).split(' ').pop(),
		m[1].match(/data-delta="(\w+)"/)?.[1] ?? ''
	]);

const tree = {
	kind: 'tree',
	props: {
		title: 'What the converge would change',
		nodes: [
			{
				label: 'nOS',
				delta: 'changed',
				children: [
					{ label: 'pupil', delta: 'added', children: [{ label: 'eye' }] },
					{ label: 'keap', delta: 'removed', children: [{ label: 'lobe' }, { label: 'cell' }] },
					{ label: 'wing' },
					{ label: 'bone' },
					{ label: 'pulse' }
				]
			}
		]
	}
};
const list = {
	kind: 'list',
	props: {
		ordered: false,
		items: [
			{ text: 'backup', delta: 'changed' },
			{ text: 'digest', delta: 'added' },
			{ text: 'sync', delta: 'removed' },
			{ text: 'red' }
		]
	}
};
const record = {
	kind: 'record',
	props: {
		fields: [
			{ key: 'status', value: 'done', delta: 'changed', was: 'open' },
			{ key: 'owner', value: 'iris', delta: 'added' },
			{ key: 'blocker', value: 'virtiofs', delta: 'removed' },
			{ key: 'track', value: 'backup' }
		]
	}
};

describe('change markers are text, and a removed parent marks its children', () => {
	it('a removed parent marks every child removed, an added one added; a changed one passes nothing', () => {
		const g = draw(tree);
		expect(g.html).toContain('data-layout="list"');
		const m = Object.fromEntries(marks(g.html));
		expect(m).toEqual({
			nOS: 'changed',
			pupil: 'added',
			eye: 'added',
			keap: 'removed',
			lobe: 'removed',
			cell: 'removed',
			wing: '',
			bone: '',
			pulse: ''
		});
		for (const s of ['− removed lobe', '− removed cell', '+ added eye', '~ changed nOS'])
			expect(g.text).toContain(s);
	});

	it('an org chart marks its nodes too', () => {
		const org = draw({
			kind: 'tree',
			props: {
				nodes: [{ label: 'root', delta: 'removed', children: [{ label: 'a' }, { label: 'b' }] }]
			}
		});
		expect(org.html).toContain('data-layout="org"');
		for (const s of ['− removed root', '− removed a', '− removed b']) expect(org.text).toContain(s);
	});

	it('the markers are text (+ − ~), not colour only', () => {
		for (const [c, want] of [
			[list, ['~ changed backup', '+ added digest', '− removed sync']],
			[record, ['~ changed status', '+ added owner', '− removed blocker']]
		] as const) {
			const g = draw(c);
			for (const s of want) expect(g.text).toContain(s);
			// The mark is a text node of its own; the colour is a var(--) token on top of it.
			expect(g.html).toMatch(/<span class="mark[^"]*"[^>]*>\+<\/span>/);
			expect(g.html).toMatch(/<span class="mark[^"]*"[^>]*>−<\/span>/);
			expect(g.html).toMatch(/<span class="mark[^"]*"[^>]*>~<\/span>/);
		}
		expect(draw(list).text).toMatch(/(^| )red( |$)/);
		expect(draw(list).text).not.toMatch(/[+−~] (added|removed|changed) red/);
	});

	it('the count row is exact: inherited marks count, unmarked items do not', () => {
		expect(draw(tree).text).toContain('+2 −3 ~1');
		expect(draw(list).text).toContain('+1 −1 ~1');
		expect(draw(record).text).toContain('+1 −1 ~1');
	});

	it('nothing marked: no count row and no switch', () => {
		const g = draw({ kind: 'list', props: { ordered: false, items: [{ text: 'a' }] } });
		expect(g.text).not.toContain('Změny');
		expect(g.text).not.toMatch(/\+\d/);
	});

	it('Před hides what is added, Po hides what is removed, Změny shows everything', () => {
		for (const v of ['before', 'changes', 'after']) {
			const g = draw(tree, v);
			for (const s of ['Před', 'Změny', 'Po']) expect(g.text).toContain(s);
			expect(g.html).toMatch(
				new RegExp(`<input[^>]*value="${v}"[^>]*checked|<input[^>]*checked[^>]*value="${v}"`)
			);
			const shown = marks(g.html).map(([label]) => label);
			const added = ['pupil', 'eye'],
				removed = ['keap', 'lobe', 'cell'];
			expect(shown.filter((l) => added.includes(l!)).length, v).toBe(v === 'before' ? 0 : 2);
			expect(shown.filter((l) => removed.includes(l!)).length, v).toBe(v === 'after' ? 0 : 3);
			expect(shown, v).toEqual(expect.arrayContaining(['nOS', 'wing', 'bone', 'pulse']));
			// The count row says the whole change in every view.
			expect(g.text).toContain('+2 −3 ~1');
		}
		expect(draw(list, 'before').text).not.toContain('digest');
		expect(draw(list, 'after').text).not.toContain('sync');
	});

	it('a changed field shows was → value in Změny, was in Před, value in Po', () => {
		expect(draw(record).text).toContain('status open → done');
		const before = draw(record, 'before').text;
		expect(before).toContain('status open');
		expect(before).not.toContain('done');
		expect(before).not.toContain('owner');
		const after = draw(record, 'after').text;
		expect(after).toContain('status done');
		expect(after).not.toContain('open');
		expect(after).not.toContain('virtiofs');
	});
});

// SSR cannot click, so the switch is read off the markup and the AST: one named group, bound to view.
describe('the Před / Změny / Po switch is one group that sets the view', () => {
	const radios = (h: string) => h.match(/<input[^>]*type="radio"[^>]*>/g) ?? [];
	const name = (i: string) => i.match(/name="([^"]+)"/)?.[1];

	it('the three radios share one name', () => {
		const a = radios(draw(list).html);
		expect(a.length).toBe(3);
		expect(
			a.map(name).every((n) => n && n === name(a[0] ?? '')),
			a.join('\n')
		).toBe(true);
	});

	it('every radio binds the bindable view, so a click is the view the body is drawn in', () => {
		type N = { type?: string; name?: string; [k: string]: unknown };
		const src = readFileSync(new URL('./Component.svelte', import.meta.url), 'utf8');
		const els: N[] = [];
		const walk = (n: unknown): void => {
			if (!n || typeof n !== 'object') return;
			if (Array.isArray(n)) return n.forEach(walk);
			if ((n as N).type === 'RegularElement' && (n as N).name === 'input') els.push(n as N);
			for (const [k, v] of Object.entries(n)) if (k !== 'metadata' && k !== 'parent') walk(v);
		};
		walk(parse(src, { modern: true }).fragment);
		const attrs = (e: N) => e.attributes as N[];
		const radio = els.filter((e) =>
			attrs(e).some((a) => a.name === 'type' && JSON.stringify(a.value).includes('"radio"'))
		);
		expect(radio.length).toBe(1);
		const group = attrs(radio[0]).find((a) => a.type === 'BindDirective' && a.name === 'group');
		expect(
			(group?.expression as N)?.type === 'Identifier' && (group?.expression as N).name,
			'bind:group={view}'
		).toBe('view');
		// $props.id() is unique per instance, so two switches on one page are two groups.
		const named = attrs(radio[0]).find((a) => a.type === 'Attribute' && a.name === 'name');
		const id = ((named?.value as N)?.expression as N)?.name;
		expect(id, 'name={<an identifier>}').toBeTruthy();
		expect(src).toMatch(new RegExp(`const ${id} = \\$props\\.id\\(\\);`));
		expect(src).toMatch(/\bview = \$bindable\(/);
	});
});

describe('an ordered list keeps the terminal numbers in every view', () => {
	const ol = {
		kind: 'list',
		props: {
			ordered: true,
			items: [{ text: 'one', delta: 'added' }, { text: 'two', delta: 'removed' }, { text: 'three' }]
		}
	};
	const values = (h: string) => [...h.matchAll(/<li[^>]*?value="(\d+)"/g)].map((m) => Number(m[1]));

	it('Před keeps 2, 3; Po keeps 1, 3; Změny 1, 2, 3 (shell.rs numbers the whole list)', () => {
		expect(values(draw(ol, 'before').html)).toEqual([2, 3]);
		expect(values(draw(ol, 'after').html)).toEqual([1, 3]);
		expect(values(draw(ol, 'changes').html)).toEqual([1, 2, 3]);
	});
});
