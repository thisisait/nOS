// @vitest-environment happy-dom
// The canvas journey (operator 2026-10-18: workspaces are an infinite canvas on Svelte Flow). One
// person's path end to end: a v2 layout loads, migrated; zoom and pan; a widget dragged and moved
// by keys; a heading and a frame added; the save is v3; a reload draws the same places.
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import fixture from '../../../../contracts/workspace-layout.fixture.json';
import Iris from './Iris.svelte';
import { fakeTransport } from './transport.fake';
import type { Layout } from './workspace';

const v2 = fixture.migrated[0].v2 as unknown as Layout; // "poc: rows, chart and form on one tab"

let app: ReturnType<typeof mount> | null = null;
// happy-dom lays nothing out: the window is 1200 x 800, or Svelte Flow auto-pans at every edge.
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

// Svelte Flow's zoom steps run on d3 timers and Iris saves 300 ms after the last change: real time.
const wait = async (ms = 60) => {
	await new Promise((r) => setTimeout(r, ms));
	flushSync();
};
const node = (id: string) =>
	document.querySelector<HTMLElement>(`.svelte-flow__node[data-id="${id}"]`);
const at = (id: string) => node(id)?.style.transform;
const button = (name: string) =>
	[...document.querySelectorAll('button')].find(
		(b) => b.getAttribute('aria-label') === name || b.textContent?.trim() === name
	)!;
const viewport = () => {
	const t = document.querySelector<HTMLElement>('.svelte-flow__viewport')!.style.transform;
	const [x, y, zoom] = (t.match(/-?[\d.]+/g) ?? []).map((n) => Math.round(Number(n) * 1000) / 1000);
	return { x, y, zoom };
};

async function open(layout: Layout) {
	const fake = fakeTransport(layout);
	app = mount(Iris, { target: document.body, props: { transport: fake.transport } });
	await wait();
	return fake;
}

const mouse = (el: EventTarget, type: string, x: number, y: number) =>
	el.dispatchEvent(
		new MouseEvent(type, {
			bubbles: true,
			cancelable: true,
			clientX: x,
			clientY: y,
			view: window,
			buttons: 1
		})
	);

describe('a workspace is a canvas', () => {
	it('loads v2, zooms and pans, moves, adds a heading and a frame, saves v3, and reloads the same', async () => {
		const fake = await open(v2);
		// v2 grid units as world px: column x100, row x48.
		expect([at('w1'), at('w2'), at('w3')]).toEqual([
			'translate(0px, 0px)',
			'translate(600px, 0px)',
			'translate(0px, 384px)'
		]);
		expect(node('w2')!.style.width).toBe('592px');
		expect(node('w2')!.textContent, 'the node is the live widget').toContain('Spend by kind');
		expect(document.querySelector('a'), 'no attribution link out of the window').toBeNull();

		button('zoom in').click();
		await wait();
		expect(button('zoom to 100%').textContent?.trim()).toBe('120%');
		expect(viewport(), 'about the middle of the window').toEqual({ x: -120, y: -80, zoom: 1.2 });

		const pane = document.querySelector('.svelte-flow__pane')!;
		mouse(pane, 'mousedown', 400, 400);
		mouse(window, 'mousemove', 440, 430);
		mouse(window, 'mouseup', 440, 430);
		await wait();
		expect(viewport(), 'dragging the background pans').toEqual({ x: -80, y: -50, zoom: 1.2 });

		// The widget's grip is its drag handle: 60 screen px at 120 % is 50 world px, snapped to 48.
		const grip = node('w1')!.querySelector('.move')!;
		mouse(grip, 'mousedown', 300, 300);
		mouse(window, 'mousemove', 302, 300); // past the 1 px threshold: the drag starts here
		mouse(window, 'mousemove', 362, 300);
		mouse(window, 'mouseup', 362, 300);
		await wait();
		expect(at('w1')).toBe('translate(48px, 0px)');

		// Keyboard: a focused node moves by arrows (8 px) and resizes by shift+arrows.
		const w3 = node('w3')!;
		w3.focus();
		w3.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
		w3.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'ArrowDown', shiftKey: true, bubbles: true })
		);
		flushSync();
		expect(at('w3')).toBe('translate(8px, 384px)');
		expect(w3.style.height).toBe(`${6 * 48 - 8 + 8}px`);

		button('+ heading').click();
		button('+ frame').click();
		flushSync();
		const heading = document.querySelector<HTMLInputElement>('input[aria-label="heading text"]')!;
		heading.value = 'Výdaje Q4';
		heading.dispatchEvent(new Event('change', { bubbles: true }));
		await wait(400);

		const saved = fake.saved.at(-1)!;
		expect(saved.version).toBe(3);
		const space = saved.workspaces[0];
		expect(space.view).toEqual({ x: -80, y: -50, zoom: 1.2 });
		const items = Object.fromEntries(
			space.items.map((i) => [i.kind === 'widget' ? i.id : i.kind, i])
		);
		expect(items.w1).toMatchObject({ kind: 'widget', x: 48, y: 0, w: 592, h: 376 });
		expect(items.w3).toMatchObject({ x: 8, y: 384, h: 288 });
		expect(items.heading).toMatchObject({ kind: 'heading', text: 'Výdaje Q4' });
		expect(items.frame).toMatchObject({ kind: 'frame', title: 'Frame' });

		unmount(app!);
		app = null;
		document.body.replaceChildren();
		await open(structuredClone(saved));
		for (const i of space.items) {
			expect(at(i.id), i.id).toBe(`translate(${i.x}px, ${i.y}px)`);
			expect(node(i.id)!.style.width, i.id).toBe(`${i.w}px`);
		}
		expect(viewport()).toEqual({ x: -80, y: -50, zoom: 1.2 });
		expect(button('zoom to 100%').textContent?.trim()).toBe('120%');
	});

	it('is driven by keys alone: Tab in reading order, arrows move, + and f zoom, a heading lands at the centre', async () => {
		// The items stored out of reading order: the tab order is still top-left first.
		const shuffled = structuredClone(v2) as unknown as { workspaces: { widgets: unknown[] }[] };
		shuffled.workspaces[0].widgets.reverse();
		await open(shuffled as unknown as Layout);
		// happy-dom does not move focus on Tab: the tab order is the DOM order of the focusable nodes.
		const order = [...document.querySelectorAll<HTMLElement>('.svelte-flow__node')]
			.filter((n) => n.tabIndex >= 0)
			.map((n) => n.dataset.id);
		expect(order, 'Tab walks top-left first').toEqual(['w1', 'w2', 'w3']);

		const w1 = node('w1')!;
		w1.focus();
		const press = (key: string) =>
			w1.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
		press('ArrowRight');
		press('ArrowDown');
		flushSync();
		expect(at('w1')).toBe('translate(8px, 8px)');

		press('+');
		await wait();
		expect(button('zoom to 100%').textContent?.trim()).toBe('120%');
		press('0');
		await wait();
		expect(button('zoom to 100%').textContent?.trim()).toBe('100%');
		press('-');
		await wait();
		expect(button('zoom to 100%').textContent?.trim()).toBe('83%');
		// happy-dom lays nothing out, so Svelte Flow's fit (button or key) never resolves here:
		// what is pinned is that the canvas takes f, as it takes + - 0, and not the page.
		expect(press('f'), 'the canvas took f').toBe(false);

		button('+ heading').click();
		flushSync();
		const id = document.querySelector<HTMLElement>('.svelte-flow__node[aria-label^="heading"]')!
			.dataset.id!;
		// The window is 1200 x 800: its centre in world px, the 400 x 48 heading centred on it.
		const v = viewport();
		const snap = (n: number) => Math.round(n / 8) * 8;
		const x = snap((600 - v.x) / v.zoom - 200),
			y = snap((400 - v.y) / v.zoom - 24);
		expect(at(id), 'the new heading sits at the centre of the view').toBe(
			`translate(${x}px, ${y}px)`
		);
	});
});
