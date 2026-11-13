<!--
  Hands Svelte Flow's instance API (useSvelteFlow) to the parent view. The hook needs the
  flow's context, so it can only be called from a component rendered INSIDE <SvelteFlow>;
  the skill tree uses it to move the camera (a bound viewport is written by the flow, but a
  write to it does not move the camera).
-->
<script lang="ts">
	import { useSvelteFlow } from '@xyflow/svelte';

	export type FlowApi = ReturnType<typeof useSvelteFlow>;
	let { onready }: { onready: (api: FlowApi) => void } = $props();
	const api = useSvelteFlow();
	$effect(() => onready(api));
</script>
