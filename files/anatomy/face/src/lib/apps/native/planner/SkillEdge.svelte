<!--
  One link of the skill tree (skill-tree v2): a radial Bézier from parent to child, routed by
  edgePath() so siblings leave their parent along one trunk and fan out (straight from the
  core, into the halo, and for tiny angles). Both handles sit on the gem centres, so the
  endpoints Svelte Flow hands in ARE the centres in flow coordinates, whose origin is the core.
  pathLength="1" lets the CSS draw the link with dash 1 / offset 1 → 0 (the grow intro and
  the ignite effect); --grow is the BFS depth that staggers it. The wrapping g carries the
  class (grown / front / trace) and data-id; the invisible wide path is the click target
  (an edge is selected, then deleted, to un-parent a row: the Roadmap graph's write).
-->
<script lang="ts">
	import type { EdgeProps } from '@xyflow/svelte';
	import { edgePath } from '$lib/tables/skilltree/routing';
	import type { GemRank } from '$lib/tables/planner';

	let { sourceX, sourceY, targetX, targetY, data, interactionWidth = 12 }: EdgeProps = $props();
	const d = $derived(
		edgePath(
			{ x: sourceX, y: sourceY, rank: (data?.sRank as GemRank) ?? 'leaf' },
			{ x: targetX, y: targetY, rank: (data?.tRank as GemRank) ?? 'leaf' }
		)
	);
</script>

<path class="svelte-flow__edge-path" {d} pathLength="1" style:--grow={String(data?.grow ?? 0)} />
<path
	{d}
	stroke-opacity="0"
	stroke-width={interactionWidth}
	fill="none"
	class="svelte-flow__edge-interaction"
/>
