<!--
  One node of the Planner's skill tree. The outer box is Svelte Flow's (it carries the
  st-<state> / rank classes the view sets and the aria-label); this draws only the gem
  and the label, so 1100 nodes stay a few cheap elements each. The label hangs below
  the gem and is shown by the view's level-of-detail class, hover, focus or selection.
  Handles stay, hidden until hover: drag-to-reparent is still the Roadmap graph's gesture.
-->
<script lang="ts">
	import { Handle, Position, type NodeProps } from '@xyflow/svelte';

	let { data }: NodeProps = $props();
</script>

<Handle type="target" position={Position.Top} />
<i class="gem" aria-hidden="true"></i>
<span class="lbl">
	{data.label}
	{#if data.tells}<small class="tells">{data.tells}</small>{/if}
</span>
<Handle type="source" position={Position.Bottom} />

<style>
	.gem {
		position: absolute;
		inset: 0;
		display: block;
		border-radius: 50%;
		background: var(--node, var(--glass-brd));
	}
	.lbl {
		position: absolute;
		top: calc(100% + 5px);
		left: 50%;
		transform: translateX(-50%) scale(var(--lbl-scale, 1));
		transform-origin: top center;
		display: none;
		flex-direction: column;
		align-items: center;
		max-width: 180px;
		padding: 2px 8px;
		border-radius: 999px;
		background: var(--glass);
		border: 1px solid var(--glass-brd);
		color: var(--fg);
		font-size: 11px;
		line-height: 1.3;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		pointer-events: none;
	}
	.tells {
		display: none;
		font-size: 10px;
		font-weight: 400;
		color: var(--muted);
		white-space: normal;
		text-align: center;
		max-width: 180px;
	}
</style>
