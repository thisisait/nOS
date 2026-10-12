<script lang="ts">
	import type { View } from './eye';
	let { view }: { view: View } = $props();
</script>

<div data-state={view.state}></div>
