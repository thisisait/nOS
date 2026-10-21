// iris-agent-dendrogram inc.1: read_run's tree is drawn on Graph.svelte, one node a run node,
// one edge a parent link, the status as the node's tone (ok ok, running info, waiting warn, bad bad).
import { readFileSync } from 'node:fs';
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Message from './Message.svelte';
import type { Component, ToShell } from './wire';

const fx = JSON.parse(
	readFileSync(
		new URL('../../../../contracts/thalamus-shell.fixture.json', import.meta.url),
		'utf8'
	)
) as { to_shell: { case: string; msg: ToShell }[] };
const sample = fx.to_shell.find(
	(c) => 'component' in c.msg && c.msg.component.kind === 'dendrogram'
)!.msg as Extract<ToShell, { t: 'render' }>;
const run = (sample.component as Extract<Component, { kind: 'dendrogram' }>).props;
const TONE = { ok: 'ok', running: 'info', waiting: 'warn', bad: 'bad' };

describe('a run tree in Iris', () => {
	const h = render(Message, { props: { msg: sample } }).body;

	it('one node per run node, its tone its status', () => {
		const tones = [...h.matchAll(/<g[^>]*class="node tone-(\w+)/g)].map((m) => m[1]);
		expect(tones).toEqual(run.nodes.map((n) => TONE[n.status]));
	});

	it('one edge per parent link, and the cap said', () => {
		expect(h.match(/<path[^>]*class="edge/g)?.length).toBe(
			run.nodes.filter((n) => n.parent).length
		);
		expect(h).toContain(`${run.hidden} more not drawn`);
	});
});
