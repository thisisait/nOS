<script lang="ts">
	/**
	 * Host that renders the correct control-panel surface for a window, decoding
	 * the surface from `win.app` (see surfaces.ts). The integrator mounts this
	 * inside the generic Window children for any window where
	 * `isControlPanelWindow(win.app)` is true.
	 */
	import { onMount } from 'svelte';
	import type { WindowModel, DataTable } from '$lib/contracts';
	import { loadTable } from '$lib/api/tables';
	import { CP_GRID_APP, parseSurfaceApp } from './surfaces';
	import ControlPanel from './ControlPanel.svelte';
	import Wallpaper from './Wallpaper.svelte';
	import DataTableApp from '$lib/components/DataTableApp.svelte';

	let { win }: { win: WindowModel } = $props();

	const parsed = $derived(win.app === CP_GRID_APP ? null : parseSurfaceApp(win.app));

	let table = $state<DataTable | null>(null);

	onMount(async () => {
		if (parsed?.surface === 'rawDataTable' && parsed.table) {
			try {
				table = await loadTable(parsed.table);
			} catch {
				table = null;
			}
		}
	});
</script>

{#if win.app === CP_GRID_APP}
	<ControlPanel />
{:else if parsed?.surface === 'wallpaper'}
	<Wallpaper />
{:else if parsed?.surface === 'rawDataTable'}
	<DataTableApp {table} />
{:else if parsed}
	<div class="ph">
		<p><strong>{win.title}</strong></p>
		<p class="muted">
			The “{parsed.surface}” editor is coming soon. For now this surface is a placeholder.
		</p>
	</div>
{/if}

<style>
	.ph {
		display: grid;
		gap: 8px;
		font-size: 13px;
	}
	.muted {
		color: var(--muted, #9aa4b2);
	}
</style>
