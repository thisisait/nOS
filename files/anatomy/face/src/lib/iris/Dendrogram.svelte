<!--
  One agent run as a tree (renderers.rs Dendrogram, read_run): the graph's layered columns
  (Graph.svelte, parent -> child), status as tone, and what serve's cap left out said.
-->
<script lang="ts">
	import Graph from './Graph.svelte';
	import type { GraphProps } from './graph/layout';
	import type { DendrogramProps } from './wire';

	let { run }: { run: DendrogramProps } = $props();

	const TONE = { ok: 'ok', running: 'info', waiting: 'warn', bad: 'bad' } as const;
	const graph: GraphProps = $derived({
		nodes: run.nodes.map((n) => {
			const when = [n.started, n.ended].filter(Boolean).join(' → ');
			const note = [n.kind, n.status, when, n.tokens ? `${n.tokens} tokens` : '', n.note ?? '']
				.filter(Boolean)
				.join(' — ');
			return { id: n.id, label: n.name, note, tone: TONE[n.status] };
		}),
		edges: run.nodes.flatMap((n) => (n.parent ? [{ from: n.parent, to: n.id }] : []))
	});
</script>

<div class="dendrogram">
	<Graph {graph} focus={run.root} />
	{#if run.hidden > 0}<p class="muted">{run.hidden} more not drawn</p>{/if}
</div>

<style>
	.muted {
		margin: 2px 0;
		font-size: 11px;
		color: var(--muted);
	}
</style>
