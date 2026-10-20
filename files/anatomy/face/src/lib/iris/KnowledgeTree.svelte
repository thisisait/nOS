<!--
  The ontology around one node of our knowledge (renderers.rs KnowledgeTree): drawn as the graph's
  layered columns (Graph.svelte, parent -> child), the read node marked, its text below, and what
  serve's cap left out said. A click on a node opens it: onread places it as a knowledge widget.
-->
<script lang="ts">
	import Graph from './Graph.svelte';
	import type { GraphProps } from './graph/layout';
	import type { KnowledgeProps } from './wire';

	let { tree, onread }: { tree: KnowledgeProps; onread?: (id: string, name: string) => void } =
		$props();

	const graph: GraphProps = $derived({
		nodes: tree.nodes.map((n) => {
			const note = [n.child_count ? `${n.child_count} under it` : '', n.text ?? '']
				.filter(Boolean)
				.join(' — ');
			return { id: n.id, label: n.name, ...(note ? { note } : {}) };
		}),
		edges: tree.nodes.flatMap((n) => (n.parent ? [{ from: n.parent, to: n.id }] : []))
	});
	const focus = $derived(tree.nodes.find((n) => n.id === tree.focus));
	const pick = (id: string) => onread?.(id, tree.nodes.find((n) => n.id === id)?.name ?? id);
</script>

<div class="knowledge">
	<Graph {graph} focus={tree.focus} onpick={onread ? pick : undefined} />
	{#if focus?.text}<p class="text"><b>{focus.name}</b> [{focus.id}]: {focus.text}</p>{/if}
	{#if tree.hidden > 0}<p class="muted">{tree.hidden} more not drawn</p>{/if}
	{#if onread}<p class="muted">click a node to open it</p>{/if}
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
</style>
