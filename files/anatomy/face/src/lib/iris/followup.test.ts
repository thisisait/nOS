// @vitest-environment happy-dom
// A follow_up prompt is the model's suggestion, never the person's turn: a click puts it in the
// composer and sends nothing (thalamus-shell.yml components.follow_up). Steps and callout say
// their state as a word, not as colour only.
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import Component from './Component.svelte';
import Iris from './Iris.svelte';
import type { ComponentProps as Props } from 'svelte';
import { fakeTransport } from './transport.fake';

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
	if (app) unmount(app);
	app = null;
	document.body.replaceChildren();
});
const wait = async (ms = 60) => {
	await new Promise((r) => setTimeout(r, ms));
	flushSync();
};

describe('the v12 kinds', () => {
	it('a follow_up click fills the composer and sends no turn', async () => {
		const fake = fakeTransport();
		app = mount(Iris, { target: document.body, props: { transport: fake.transport } });
		await wait();
		fake.shell({
			t: 'render',
			session: '0b6f6a1e-3c2d-4e5f-8a9b-0c1d2e3f4a5b',
			component: { kind: 'follow_up', props: { prompts: ['Chart this by month'] } }
		});
		await wait();
		const before = fake.sent.length;
		const b = [...document.querySelectorAll('button')].find(
			(x) => x.textContent?.trim() === 'Chart this by month'
		)!;
		expect(b.disabled).toBe(false);
		b.click();
		await wait();
		expect(document.querySelector('textarea')!.value).toBe('Chart this by month');
		expect(fake.sent.slice(before).filter((m) => m.t === 'turn')).toEqual([]);
	});

	const draw = (component: Props<typeof Component>['component']) => {
		app = mount(Component, { target: document.body, props: { component } });
		flushSync();
		return document.body;
	};

	it('a follow_up with no composer is drawn but not clickable', () => {
		const b = draw({ kind: 'follow_up', props: { prompts: ['Next?'] } }).querySelector('button')!;
		expect([b.textContent, b.disabled]).toEqual(['Next?', true]);
	});

	it('a step and a callout say their state as a word', () => {
		const steps = draw({
			kind: 'steps',
			props: { items: [{ title: 'Fetch', status: 'active', detail: 'timeout' }] }
		}).textContent!;
		expect(steps).toMatch(/active\s*Fetch — timeout/);
		unmount(app!);
		const note = draw({
			kind: 'callout',
			props: { tone: 'bad', title: 'Risk', text: 'No backup.' }
		}).querySelector('[role="note"]')!.textContent!;
		expect(note).toMatch(/bad\s*Risk\s*No backup\./);
	});

	// The marker is the shell's, not a prop: a model callout never reads as the thalamus's own warning.
	it('a callout is headed "Iris says" by the shell', () => {
		const note = draw({
			kind: 'callout',
			props: { tone: 'bad', title: 'Risk', text: 'No backup.' }
		}).querySelector('[role="note"]')!;
		expect(note.textContent).toMatch(/^\s*Iris says/);
		expect(note.getAttribute('aria-label')).toBe('Iris says: Risk');
	});
});
