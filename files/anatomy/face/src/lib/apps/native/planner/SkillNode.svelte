<!--
  One node of the Planner's skill tree. The outer box is Svelte Flow's (it carries the
  st-<state> / rank classes the view sets and the aria-label); this draws only the gem, so
  1100 nodes stay a few cheap elements each. The name is NOT here: the view's label layer
  places names in screen space by a collision pass (labelPlan), so no text ever scales with
  the zoom or lands on another. The full title is the gem's tooltip.
  Both handles sit on the gem's centre, so an edge meets the centre; drag-to-reparent is
  still the Roadmap graph's gesture (a handle is a drag target only on hover).
-->
<script lang="ts">
	import { Handle, Position, type NodeProps } from '@xyflow/svelte';

	let { data }: NodeProps = $props();
</script>

<Handle type="target" position={Position.Top} />
<i class="gem" aria-hidden="true" title={String(data.title ?? '')}></i>
<Handle type="source" position={Position.Bottom} />

<style>
	.gem {
		position: absolute;
		inset: 0;
		display: block;
		border-radius: 50%;
		background: var(--node, var(--glass-brd));
	}
</style>
