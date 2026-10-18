// @vitest-environment happy-dom
// The nested-boards journey (roadmap iris-canvas-nested-boards): a board on the canvas opens a child
// workspace; the breadcrumb is the path workspaces://<id>/<id>; opening one resumes its own session;
// a reload lands on the same path and runs only that board's widgets; Escape goes up; a deleted
// board takes its subtree with it.
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import fixture from '../../../../contracts/workspace-layout.fixture.json';
import Iris from './Iris.svelte';
import { fakeTransport } from './transport.fake';
import type { ToShell } from './wire';
import type { Layout } from './workspace';

const poc = fixture.samples[0].layout as unknown as Layout; // root "main": w1, w2, w3

let app: ReturnType<typeof mount> | null = null;
const rect = HTMLElement.prototype.getBoundingClientRect;
beforeEach(() => {
	HTMLElement.prototype.getBoundingClientRect = () =>
		({
			x: 0,
			y: 0,
			left: 0,
			top: 0,
			right: 1200,
			bottom: 800,
			width: 1200,
			height: 800
		}) as DOMRect;
});
afterEach(() => {
	HTMLElement.prototype.getBoundingClientRect = rect;
	if (app) unmount(app);
	app = null;
	document.body.replaceChildren();
});

const wait = async (ms = 60) => {
	await new Promise((r) => setTimeout(r, ms));
	flushSync();
};
const button = (name: string) =>
	[...document.querySelectorAll('button')].find(
		(b) => b.getAttribute('aria-label') === name || b.textContent?.trim() === name
	);
const nav = () => document.querySelector<HTMLElement>('nav[aria-label="workspace path"]')!;
const crumbs = () => [...nav().querySelectorAll('ol > li')].map((li) => li.textContent?.trim());
const current = () => nav().querySelector('[aria-current="page"]')?.textContent?.trim();
const card = (name: string) =>
	document.querySelector<HTMLElement>(`.svelte-flow__node[aria-label="board ${name}"]`);
const key = (el: Element, k: string) =>
	el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }));
const ran = (sent: { t: string }[]) =>
	sent.filter((m) => m.t === 'widget').map((m) => (m as { widget: string }).widget);
const pinned: ToShell = {
	t: 'render',
	session: '0b6f6a1e-3c2d-4e5f-8a9b-0c1d2e3f4a5b',
	component: {
		kind: 'chart',
		props: {
			title: 'Q4 by kind',
			chart: 'pie',
			x: 'category',
			series: [{ name: 's', points: [['a', 1]] }]
		}
	},
	pin: { chart: { query: { table: 'expenses' }, chart: 'pie', x: 'kind', y: 'amount', op: 'sum' } }
};

async function open(layout: Layout) {
	const fake = fakeTransport(layout);
	app = mount(Iris, { target: document.body, props: { transport: fake.transport } });
	await wait();
	return fake;
}

describe('boards nest', () => {
	it('opens a board by path, pins there, reloads onto it, goes up by Escape, deletes a subtree', async () => {
		const fake = await open(structuredClone(poc));
		expect(document.querySelector('[role="tab"]'), 'the breadcrumb replaced the tabs').toBeNull();
		expect(crumbs()).toEqual(['Expenses']);
		expect(current()).toBe('Expenses');
		expect(nav().title).toBe('workspaces://main');

		button('+ board')!.click();
		await wait();
		const b = card('Board')!;
		expect(b, 'a board card on the canvas').not.toBeNull();
		expect(b.textContent).toContain('0 items');

		// Enter on the card opens it: the breadcrumb is the path, the board's own session resumes.
		b.focus();
		key(b, 'Enter');
		await wait();
		expect(crumbs()).toEqual(['Expenses', 'Board']);
		expect(current()).toBe('Board');
		const child = nav().title.split('/').at(-1)!;
		expect(nav().title).toBe(`workspaces://main/${child}`);
		expect(fake.sent.at(-1)).toEqual({ t: 'resume', workspace: child });

		// "Sem" pins to the open board; a board inside it is its subtree.
		fake.shell(pinned);
		await wait();
		button('Sem')!.click();
		button('+ board')!.click();
		await wait(400);
		const saved = fake.saved.at(-1)!;
		expect(saved.active).toBe(child);
		const here = saved.workspaces.find((s) => s.id === child)!;
		expect(here.parent).toBe('main');
		expect(here.items.map((i) => i.kind)).toEqual(['widget', 'board']);
		const grand = saved.workspaces.find((s) => s.parent === child)!;
		expect(grand, 'the board inside it').toBeDefined();
		const widget = here.items[0].id;

		// Reload: the same path, and only this board's widget runs.
		unmount(app!);
		app = null;
		document.body.replaceChildren();
		const again = await open(structuredClone(saved));
		expect(crumbs()).toEqual(['Expenses', 'Board']);
		expect(nav().title).toBe(`workspaces://main/${child}`);
		expect(again.sent[0]).toEqual({ t: 'resume', workspace: child });
		expect(ran(again.sent)).toEqual([widget]);

		// Escape goes up one level: main's widgets run when it is shown, and its session resumes.
		key(document.querySelector('.svelte-flow__pane')!, 'Escape');
		await wait();
		expect(crumbs()).toEqual(['Expenses']);
		expect(again.sent.at(-1)).toEqual({ t: 'resume', workspace: 'main' });
		expect(ran(again.sent).sort()).toEqual([widget, 'w1', 'w2', 'w3'].sort());
		key(document.querySelector('.svelte-flow__pane')!, 'Escape');
		await wait();
		expect(crumbs(), 'a root has no level above').toEqual(['Expenses']);

		// Removing the card asks first; yes deletes the board and the board inside it, no orphans.
		const c = card('Board')!;
		expect(c.textContent).toContain('2 items');
		c.querySelector<HTMLButtonElement>('button[aria-label="remove board"]')!.click();
		flushSync();
		expect(card('Board'), 'nothing is deleted before the answer').not.toBeNull();
		button('delete')!.click();
		await wait(400);
		const after = again.saved.at(-1)!;
		expect(after.workspaces.map((s) => s.id)).toEqual(['main']);
		expect(after.workspaces[0].items.map((i) => i.kind)).toEqual(['widget', 'widget', 'widget']);
		expect(card('Board')).toBeNull();
	});

	it('lists the roots in the first crumb, where a new workspace starts', async () => {
		const fake = await open(structuredClone(poc));
		button('+ new workspace')!.click();
		await wait();
		expect(crumbs()).toEqual(['Workspace 2']);
		const roots = [...nav().querySelectorAll('details li button')].map((b) =>
			b.textContent?.trim()
		);
		expect(roots).toEqual(['Expenses', 'Workspace 2', '+ new workspace']);
		button('Expenses')!.click();
		await wait();
		expect(crumbs()).toEqual(['Expenses']);
		expect(fake.sent.at(-1)).toEqual({ t: 'resume', workspace: 'main' });
	});
});
