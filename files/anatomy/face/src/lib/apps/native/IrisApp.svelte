<!--
  Iris in a face window: the same components as the pupil, on the BFF's optic nerve
  (lib/iris/transport.web.ts). The transport closes with the window, and the stream with it.
-->
<script lang="ts">
	import { onDestroy } from 'svelte';
	import Iris from '$lib/iris/Iris.svelte';
	import type { Transport } from '$lib/iris/transport';
	import { webTransport } from '$lib/iris/transport.web';

	let { transport = webTransport() }: { transport?: Transport & { close?(): void } } = $props();
	onDestroy(() => transport.close?.());
</script>

<!-- contain: the floating chat is position: fixed; here it floats in this window, not the desktop. -->
<div class="iris">
	<Iris {transport} />
</div>

<style>
	.iris {
		height: 100%;
		overflow: auto;
		contain: layout paint;
	}
</style>
