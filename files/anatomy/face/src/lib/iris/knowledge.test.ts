// @vitest-environment happy-dom
// iris-grounded-knowledge: read_node draws the ontology around a node (renderers.rs KnowledgeTree) as the
// graph's layered columns, at most serve's cap with the rest said, and a click on a node offers to open it
// on a new board as a knowledge widget the thalamus reads without the model (operator 2026-10-21).
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import Iris from './Iris.svelte';
import { fakeTransport } from './transport.fake';
import type { ToShell } from './wire';

const S = '0b6f6a1e-3c2d-4e5f-8a9b-0c1d2e3f4a5b';
const RUST = '02.02.03.01.03';
const chain = [
	{ id: '02', name: 'Formal Sciences', child_count: 4 },
	{ id: '02.02', name: 'Computer Science', parent: '02', child_count: 6 },
	{ id: '02.02.03.01', name: 'Systems Languages', parent: '02.02', child_count: 60 },
	{
		id: RUST,
		name: 'Rust',
		parent: '02.02.03.01',
		child_count: 1,
		text: 'Memory-safe through ownership.'
	},
	{ id: `${RUST}.01`, name: 'Ownership', parent: RUST }
];
const siblings = Array.from({ length: 45 }, (_, i) => ({
	id: `02.02.03.01.${i + 10}`,
	name: `Sibling ${i + 10}`,
	parent: '02.02.03.01'
}));
const read: ToShell = {
	t: 'render',
	session: S,
	component: {
		kind: 'knowledge_tree',
		props: {
			title: 'Rust in our knowledge',
			focus: RUST,
			hidden: 16,
			nodes: [...chain, ...siblings]
		}
	},
	pin: { knowledge: { node: RUST } }
};

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
	if (app) unmount(app);
	app = null;
	document.body.replaceChildren();
});

const settle = async () => {
	for (let i = 0; i < 20; i++) await Promise.resolve();
	flushSync();
};

describe('a knowledge tree in Iris', () => {
	it('draws every node serve sent and no more, says the rest, and a click opens a node on a new board', async () => {
		const fake = fakeTransport();
		app = mount(Iris, { target: document.body, props: { transport: fake.transport } });
		await settle();
		fake.shell(read);
		await settle();
		const tree = document.querySelector('[data-kind="knowledge_tree"]')!;
		expect(tree, 'drawn').not.toBeNull();
		const nodes = [...tree.querySelectorAll('g.node')];
		expect(nodes).toHaveLength(50);
		expect(tree.textContent).toContain('16 more not drawn');
		expect(tree.querySelector('g.node.focus title')?.textContent).toContain(RUST);
		expect(tree.textContent).toContain('Memory-safe through ownership.');
		// Pinnable like any widget: the render carries serve's spec.
		const buttons = [...document.querySelectorAll('button')].map((b) => b.textContent?.trim());
		expect(buttons).toContain('Sem');
		const own = nodes.find((n) => n.querySelector('title')?.textContent?.includes(`${RUST}.01`))!;
		(own as unknown as HTMLElement).dispatchEvent(new MouseEvent('click', { bubbles: true }));
		await settle();
		expect(
			fake.sent.some((m) => m.t === 'widget'),
			'a click alone runs nothing'
		).toBe(false);
		const go = [...document.querySelectorAll('button')].find(
			(b) => b.textContent?.trim() === 'Open in a new board'
		)!;
		go.click();
		await settle();
		const crumb = document.querySelector('nav[aria-label="workspace path"] [aria-current="page"]');
		expect(crumb?.textContent?.trim(), 'a new board, named for the node').toBe('Ownership');
		expect(fake.sent).toContainEqual({
			t: 'widget',
			widget: expect.any(String),
			spec: { knowledge: { node: `${RUST}.01` } },
			trigger: 'click'
		});
	});
});
