<script lang="ts" module>
	import { openWindow } from '$lib/stores/desktop';
	import { CP_GRID_APP, surfaceApp } from './surfaces';
	import type { ControlEntry } from '$lib/contracts';

	/** Open (or re-open) the control-panel grid window. */
	export function openControlPanel(): string {
		return openWindow({
			app: CP_GRID_APP,
			title: 'Control Panel',
			w: 560,
			h: 420
		});
	}

	/** Open a window hosting the surface for one control entry. */
	export function openSurface(entry: ControlEntry): string {
		return openWindow({
			app: surfaceApp(entry),
			title: entry.name,
			w: entry.surface === 'rawDataTable' ? 720 : 560,
			h: 460
		});
	}
</script>

<script lang="ts">
	/**
	 * Control Panel — the first DataTable rendered as an ICON GRID (not a grid
	 * view / gallery). Each row is a config surface; clicking a row OPENS A WINDOW
	 * hosting that surface (see ControlPanelSurface.svelte).
	 */
	import { onMount } from 'svelte';
	import { loadTable } from '$lib/api/tables';
	import { controlsFromTable, FALLBACK_CONTROLS } from './surfaces';

	let entries = $state<ControlEntry[]>(FALLBACK_CONTROLS);

	onMount(async () => {
		try {
			entries = controlsFromTable(await loadTable('face-controls'));
		} catch {
			entries = FALLBACK_CONTROLS;
		}
	});
</script>

<div class="cp">
	<div class="grid">
		{#each entries as entry (entry.slug)}
			<button class="tile" title={entry.name} onclick={() => openSurface(entry)}>
				<span class="ico">{entry.icon}</span>
				<span class="lbl">{entry.name}</span>
			</button>
		{/each}
	</div>
</div>

<style>
	.cp {
		font-size: 13px;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(88px, 1fr));
		gap: 14px;
	}
	.tile {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
		background: none;
		border: none;
		cursor: pointer;
		padding: 6px;
		border-radius: 10px;
	}
	.tile:hover {
		background: rgba(255, 255, 255, 0.06);
	}
	.ico {
		width: 48px;
		height: 48px;
		display: grid;
		place-items: center;
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.08);
		font-size: 22px;
	}
	.lbl {
		font-size: 11px;
		color: var(--muted, #9aa4b2);
		text-align: center;
	}
</style>
