<!--
  Planner — two views of the estate's own work (face-planner).

  Roadmap: the roadmap DataTable as an interactive Svelte Flow graph (drag to
  reparent, RBAC-gated write-back; the DataTable stays source of truth).
  Loops:   the agentic loop's harness (propose→judge→apply + roles + intents +
  what it refuses), read-only, compiled from ledger.py.

  The shell owns only which view is active; each view fetches/imports its own
  data — same spine as the Anatomy app.
-->
<script lang="ts">
	import { Tabs, type TabSpec } from '$lib/components/ui';
	import RoadmapGraph from './RoadmapGraph.svelte';
	import LoopsView from './LoopsView.svelte';

	const tabs: TabSpec[] = [
		{ key: 'roadmap', label: 'Roadmap' },
		{ key: 'loops', label: 'Loops' }
	];
	let active = $state('roadmap');
</script>

<div class="planner-shell">
	<Tabs {tabs} bind:active label="Planner views" />
	<div class="body" role="tabpanel" id="panel-{active}" aria-labelledby="tab-{active}">
		{#if active === 'roadmap'}
			<RoadmapGraph />
		{:else if active === 'loops'}
			<LoopsView />
		{/if}
	</div>
</div>

<style>
	.planner-shell {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
	}
	.body {
		flex: 1 1 auto;
		min-height: 0;
	}
</style>
