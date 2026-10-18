// genui I6: a render's pin becomes a widget by the person's click on "Připnout na plochu", never by a
// message. The widget keeps the spec only: it re-runs as the person, so no rows or model numbers are stored.
import { readFileSync } from 'node:fs';
import { parse } from 'svelte/compiler';
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Message from './Message.svelte';
import type { Component, ToShell, WidgetSpec } from './wire';
import { route } from './widgets';
import { addSpace, empty, pin, widgetsOf } from './workspace';

const S = '0b6f6a1e-3c2d-4e5f-8a9b-0c1d2e3f4a5b';
const pie: Component = {
	kind: 'chart',
	props: {
		title: 'Expenses by kind',
		chart: 'pie',
		x: 'category',
		series: [
			{
				name: 'sum of amount',
				points: [
					['travel', 120],
					['food', 42]
				]
			}
		]
	}
};
const chartPin: WidgetSpec = {
	chart: { query: { table: 'expenses' }, chart: 'pie', x: 'kind', y: 'amount', op: 'sum' }
};
const rowsPin: WidgetSpec = {
	rows: {
		table: 'expenses',
		where: [{ column: 'kind', op: 'eq', value: 'food' }],
		group_by: 'kind'
	}
};
const table: Component = {
	kind: 'table_results',
	props: {
		table: 'expenses',
		name: 'Expenses',
		query: 'kind = food',
		matched: 1,
		total: 3,
		columns: ['kind', 'count'],
		projected: false,
		rows: [{ __id: 'food', cells: { kind: 'food', count: 1 } }]
	}
};
const sourced: ToShell = { t: 'render', session: S, component: pie, pin: chartPin };
const picture: ToShell = { t: 'render', session: S, component: pie };
const rows: ToShell = { t: 'render', session: S, component: table, pin: rowsPin };
const list: ToShell = {
	t: 'render',
	session: S,
	component: { kind: 'list', props: { ordered: false, items: [{ text: 'x' }] } }
};

const html = (msg: ToShell) => render(Message, { props: { msg, onpin: () => {} } }).body;
const BUTTON = 'Připnout na plochu'; // the group's accessible name; its face is an icon and "pin"
const HERE = 'Připnout sem',
	FRESH = 'Připnout na novou plochu';
const NOTE = 'jen náhled — Iris neuvedla zdroj čísel';

describe('the pin buttons and the preview note', () => {
	it('the buttons are drawn only for a render with a pin', () => {
		for (const m of [sourced, rows]) {
			expect(html(m)).toContain(`aria-label="${BUTTON}"`);
			// Operator 2026-10-14: small, an icon and the word pin; 2026-10-18: the person picks the tab.
			expect(html(m)).toMatch(/<svg[^>]*aria-hidden="true"[\s\S]*<\/svg>\s*pin/);
			expect(html(m)).toMatch(
				new RegExp(`<button[^>]*aria-label="${HERE}"[^>]*>\\s*Sem\\s*</button>`)
			);
			expect(html(m)).toMatch(
				new RegExp(`<button[^>]*aria-label="${FRESH}"[^>]*>\\s*Nová plocha\\s*</button>`)
			);
		}
		for (const m of [picture, list]) expect(html(m)).not.toContain(BUTTON);
	});

	it('a chart without a pin says it is a preview, and has no button', () => {
		expect(html(picture)).toContain(NOTE);
		for (const m of [sourced, rows, list]) expect(html(m)).not.toContain(NOTE);
	});
});

describe('a click places the pin', () => {
	const two = addSpace(empty(), 'ws2', 'Two');

	it('adds exactly one widget to the active tab, holding the spec and no rows, and runs it once', () => {
		const r = pin(two, {}, 'w1', sourced);
		const [ws1, ws2] = r.layout.workspaces;
		expect([ws1.items.length, ws2.items.length]).toEqual([0, 1]);
		const box = widgetsOf(ws2)[0];
		expect(box.spec).toEqual(chartPin);
		expect(Object.keys(box).sort()).toEqual(['h', 'id', 'kind', 'spec', 'title', 'w', 'x', 'y']);
		expect(box.title).toBe('Expenses by kind');
		expect(JSON.stringify(r.layout), "the model's numbers are not stored").not.toMatch(
			/120|42|travel/
		);
		expect(r.w.w1).toEqual({ component: null, error: null, at: 0, spec: chartPin });
		expect(r.send).toEqual({ t: 'widget', widget: 'w1', spec: chartPin, trigger: 'click' });
	});

	// Live 2026-10-14: the log keeps messages in $state, so msg.pin is a Proxy, and structuredClone
	// threw DataCloneError on the click: nothing was pinned and nothing was said.
	it('a pin held in reactive state (a Proxy) still places a plain copy', () => {
		const proxied = (o: object): object =>
			new Proxy(o, {
				get: (t, k) => {
					const v = Reflect.get(t, k);
					return v && typeof v === 'object' ? proxied(v) : v;
				}
			});
		const m = { ...sourced, pin: proxied(structuredClone(chartPin)) } as ToShell;
		const r = pin(two, {}, 'w4', m);
		expect(widgetsOf(r.layout.workspaces[1])[0].spec).toEqual(chartPin);
		expect(() => structuredClone(r.layout)).not.toThrow();
	});

	it('a table pin is titled by its table name; the stored spec is a copy', () => {
		const m = structuredClone(rows);
		const r = pin(two, {}, 'w2', m);
		(m as { pin: { rows: Record<string, unknown> } }).pin.rows.table = 'changed';
		expect(widgetsOf(r.layout.workspaces[1])[0]).toMatchObject({
			title: 'Expenses',
			spec: rowsPin
		});
	});

	// iris-canvas-nested-boards: a new board is a child of the open one, reached by its card there.
	it('"Nová plocha" makes one new active board inside the open one, holding just that widget', () => {
		const r = pin(two, {}, 'w5', sourced, 'ws3');
		expect(r.layout.workspaces.length).toBe(3);
		expect(r.layout.active).toBe('ws3');
		expect(r.layout.workspaces[2].parent).toBe('ws2');
		expect(widgetsOf(r.layout.workspaces[2]).map((x) => [x.id, x.spec])).toEqual([
			['w5', chartPin]
		]);
		expect(r.layout.workspaces[0]).toEqual(two.workspaces[0]);
		expect(r.layout.workspaces[1].items).toMatchObject([{ kind: 'board', board: 'ws3' }]);
	});

	it('a render without a pin places nothing', () => {
		for (const m of [picture, list])
			expect(pin(two, {}, 'w3', m)).toEqual({ layout: two, w: {}, send: null });
	});
});

type Node = { type?: string; name?: string; [k: string]: unknown };

/** Every node of `ast` with its ancestors, outermost first. */
function walk(n: unknown, up: Node[], out: [Node, Node[]][]) {
	if (!n || typeof n !== 'object') return;
	if (Array.isArray(n)) return n.forEach((x) => walk(x, up, out));
	const node = n as Node;
	if (node.type) out.push([node, up]);
	for (const [k, v] of Object.entries(node))
		if (k !== 'metadata' && k !== 'parent') walk(v, node.type ? [...up, node] : up, out);
}

const nodes = (file: string) => {
	const ast = parse(readFileSync(new URL(file, import.meta.url), 'utf8'), {
		modern: true
	}) as unknown as { fragment: unknown; instance: unknown };
	const t: [Node, Node[]][] = [],
		s: [Node, Node[]][] = [];
	walk(ast.fragment, [], t);
	walk(ast.instance, [], s);
	return { template: t, script: s };
};
const attr = (up: Node[]) => [...up].reverse().find((a) => a.type === 'Attribute')?.name;
const named = (all: [Node, Node[]][], name: string) =>
	all.filter(([n]) => n.type === 'Identifier' && n.name === name);

describe('nothing adds a widget without a click', () => {
	it("a pinned render is the log's, not a widget answer", () => {
		expect(route({}, sourced, 1)).toBeNull();
	});

	it('Message calls onpin only from a click', () => {
		const { template, script } = nodes('./Message.svelte');
		const uses = named(template, 'onpin');
		expect(uses.length).toBeGreaterThan(0);
		expect(uses.map(([, up]) => attr(up))).toEqual(uses.map(() => 'onclick'));
		expect(
			named(script, 'onpin').filter(
				([n, up]) => up.at(-1)?.type === 'CallExpression' && up.at(-1)?.callee === n
			)
		).toEqual([]);
		// The script names onpin only in its $props() declaration: an alias or an effect would call it unclicked.
		const inProps = (up: Node[]) =>
			up.some(
				(a) =>
					a.type === 'VariableDeclarator' && ((a.init as Node)?.callee as Node)?.name === '$props'
			);
		expect(
			named(script, 'onpin')
				.filter(([, up]) => !inProps(up))
				.map(([n]) => n.start)
		).toEqual([]);
	});

	it('Iris places a pin only in the handler it gives Message as onpin', () => {
		const { template, script } = nodes('./Iris.svelte');
		const calls = script.filter(
			([n]) =>
				n.type === 'CallExpression' &&
				(n.callee as Node)?.type === 'MemberExpression' &&
				((n.callee as Node).property as Node)?.name === 'pin'
		);
		expect(calls.length).toBe(1);
		const fn = calls[0][1].filter((a) => a.type === 'FunctionDeclaration').at(-1);
		expect((fn?.id as Node)?.name).toBe('pinned');
		expect(named(template, 'pinned').map(([, up]) => attr(up))).toEqual(['onpin']);
		// The script names pinned only where it declares it: a call on an incoming render pins unclicked.
		expect(
			named(script, 'pinned').map(
				([n, up]) => up.at(-1)?.type === 'FunctionDeclaration' && up.at(-1)?.id === n
			)
		).toEqual([true]);
	});
});
