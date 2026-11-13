<!--
  One node of the Planner's skill tree. The outer box is Svelte Flow's (it carries the
  st-<state> / rank classes the view sets, the aria-label and the roving tabindex); this
  draws only the gem, so 1100 nodes stay a few cheap elements each. The name is NOT here:
  the view's label layer places names in screen space (measured, wrapped, thinned by a
  collision pass), so no text ever scales with the zoom or lands on another. The full title
  is the gem's tooltip. Both handles sit on the gem's centre, so an edge meets the centre;
  drag-to-reparent is still the Roadmap graph's gesture (a handle is a drag target only on
  hover). --min keeps a gem legible at fit: on-screen size ≥ box × --min (needs the view's
  --zoom; scale 1 without it).
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
		box-sizing: border-box;
		border-radius: 50%;
		background: var(--node, var(--glass-brd));
		scale: max(1, calc(var(--min, 0) / var(--zoom, 1)));
	}
</style>
