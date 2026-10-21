<!--
  The ontology around one node of our knowledge (renderers.rs KnowledgeTree): drawn as the graph's
  layered columns (Graph.svelte, parent -> child), the read node marked, its text below, and what
  serve's cap left out said. A click on a node offers: onread opens it on a new board as a knowledge
  widget; onexpand (a widget's) draws its children here from that widget re-run for the node, `open`.
-->
<script lang="ts">
	import Graph from './Graph.svelte';
	import type { GraphProps } from './graph/layout';
	import type { WidgetState } from './widgets';
	import type { KnowledgeProps } from './wire';

	let {
		tree,
		onread,
		open = {},
		onexpand
	}: {
		tree: KnowledgeProps;
		onread?: (id: string, name: string) => void;
		open?: Record<string, WidgetState | undefined>;
		onexpand?: (id: string) => void;
	} = $props();

	// The contract's cap on one tree; what an expansion would add past it is said as hidden.
	const MAX = 200;
	const grown = $derived.by(() => {
		const nodes = [...tree.nodes];
		const ids = new Set(nodes.map((n) => n.id));
		let more = 0;
		// In the order expanded, so a grandchild's children join once its parent's did; a collapsed one's stay out.
		for (const [id, st] of Object.entries(open)) {
			const c = st?.component;
			if (c?.kind !== 'knowledge_tree' || !ids.has(id)) continue;
			for (const n of c.props.nodes) {
				if (n.parent !== id || ids.has(n.id)) continue;
				if (nodes.length >= MAX) more++;
				else {
					nodes.push(n);
					ids.add(n.id);
				}
			}
		}
		return { nodes, hidden: tree.hidden + more };
	});
	const graph: GraphProps = $derived({
		nodes: grown.nodes.map((n) => {
			const note = [n.child_count ? `${n.child_count} under it` : '', n.text ?? '']
				.filter(Boolean)
				.join(' — ');
			return { id: n.id, label: n.name, ...(note ? { note } : {}) };
		}),
		edges: grown.nodes.flatMap((n) => (n.parent ? [{ from: n.parent, to: n.id }] : []))
	});
	const focus = $derived(tree.nodes.find((n) => n.id === tree.focus));
	const nameOf = (id: string) => grown.nodes.find((n) => n.id === id)?.name ?? id;
	let picked: string | null = $state(null);
	const chosen = $derived(grown.nodes.find((n) => n.id === picked));
	const waiting = $derived(Object.entries(open).filter(([, st]) => !st?.component && !st?.error));
	const failed = $derived(Object.entries(open).filter(([, st]) => st?.error));
	const done = (f: (id: string) => void) => () => {
		if (picked) f(picked);
		picked = null;
	};
</script>

<div class="knowledge">
	<Graph
		{graph}
		focus={tree.focus}
		onpick={onread || onexpand ? (id) => (picked = id) : undefined}
	/>
	{#if chosen}
		<div class="pick" role="group" aria-label="node {chosen.name}">
			<b>{chosen.name}</b>
			{#if onread}
				<button type="button" onclick={done((id) => onread(id, nameOf(id)))}
					>Open in a new board</button
				>
			{/if}
			{#if onexpand}
				<button
					type="button"
					disabled={chosen.child_count === 0 && !(chosen.id in open)}
					onclick={done(onexpand)}
					>{chosen.id in open ? 'Collapse its children' : 'Expand its children here'}</button
				>
			{/if}
			<button type="button" class="ghost" aria-label="close" onclick={() => (picked = null)}
				>×</button
			>
		</div>
	{/if}
	{#if focus?.text}<p class="text"><b>{focus.name}</b> [{focus.id}]: {focus.text}</p>{/if}
	{#each waiting as [id]}<p class="muted">loading the children of {nameOf(id)}</p>{/each}
	{#each failed as [id, st]}<p class="muted">
			the children of {nameOf(id)} were not drawn: {st?.error}
		</p>{/each}
	{#if grown.hidden > 0}<p class="muted">{grown.hidden} more not drawn</p>{/if}
	{#if onexpand}<p class="muted">click a node to open it or expand its children</p>
	{:else if onread}<p class="muted">click a node to open it</p>{/if}
</div>

<style>
	.text {
		margin: 4px 0;
		font-size: 12px;
		line-height: 1.45;
	}
	.muted {
		margin: 2px 0;
		font-size: 11px;
		color: var(--muted);
	}
	.pick {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
		margin: 4px 0;
		font-size: 12px;
	}
	.pick button {
		border: 1px solid var(--glass-brd);
		border-radius: 8px;
		background: var(--glass);
		color: var(--fg);
		padding: 2px 8px;
		cursor: pointer;
	}
	.pick .ghost {
		border: 0;
		background: none;
		color: var(--muted);
	}
	.pick button:disabled {
		opacity: 0.4;
	}
</style>
