<script lang="ts">
	/**
	 * Wallpaper picker (control-panel surface).
	 *
	 * Reads the `face-wallpapers` DataTable (repo seed + user rows), falling back
	 * to the built-in aurora/graphite/sunset/forest gradients if the table is
	 * empty or KEAP is down. Clicking a swatch sets + persists the active
	 * wallpaper via the wallpaper store. Backgrounds are applied through
	 * `safeBackground()` only — no raw string ever reaches the DOM.
	 */
	import { onMount } from 'svelte';
	import { loadTable, tablesUpsertRow } from '$lib/api/tables';
	import { ApiError } from '$lib/api/client';
	import RowEditor from '$lib/components/RowEditor.svelte';
	import {
		activeWallpaper,
		setWallpaper,
		wallpapersFromTable,
		safeBackground,
		FALLBACK_WALLPAPERS
	} from '$lib/state/wallpaper';
	import type { WallpaperSpec, DataTable } from '$lib/contracts';

	let choices = $state<WallpaperSpec[]>(FALLBACK_WALLPAPERS);
	let table = $state<DataTable | null>(null);
	let editing = $state(false);
	let submitting = $state(false);
	let saveErr = $state('');

	async function reload() {
		try {
			table = await loadTable('face-wallpapers');
			choices = wallpapersFromTable(table);
		} catch {
			choices = FALLBACK_WALLPAPERS;
		}
	}
	onMount(reload);

	async function save(row: Record<string, unknown>) {
		submitting = true;
		saveErr = '';
		try {
			await tablesUpsertRow('face-wallpapers', row);
			await reload();
			editing = false;
		} catch (e) {
			saveErr = e instanceof ApiError ? e.message : 'save failed';
		} finally {
			submitting = false;
		}
	}
</script>

<div class="picker">
	<div class="head">
		<p class="muted">Choose a desktop wallpaper.</p>
		{#if table?.canWrite}
			<button
				class="add"
				onclick={() => {
					saveErr = '';
					editing = true;
				}}>＋ Add wallpaper</button
			>
		{/if}
	</div>
	<div class="grid">
		{#each choices as wp (wp.slug)}
			{@const bg = safeBackground(wp)}
			<button
				class="swatch"
				class:active={$activeWallpaper.slug === wp.slug}
				title={wp.name}
				aria-label={wp.name}
				aria-pressed={$activeWallpaper.slug === wp.slug}
				onclick={() => setWallpaper(wp)}
			>
				<span class="preview" style={bg ? `background:${bg}` : ''}></span>
				<span class="name">{wp.name}</span>
			</button>
		{/each}
	</div>
</div>

{#if editing && table}
	<div class="scrim" role="presentation" onclick={() => (editing = false)}></div>
	<div class="modal">
		<RowEditor
			{table}
			{submitting}
			error={saveErr}
			onsubmit={save}
			oncancel={() => (editing = false)}
		/>
	</div>
{/if}

<style>
	.picker {
		display: flex;
		flex-direction: column;
		gap: 12px;
		font-size: 13px;
	}
	.head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}
	.add {
		background: rgba(90, 150, 255, 0.85);
		color: #fff;
		border: none;
		border-radius: 8px;
		padding: 6px 12px;
		font-size: 12px;
		cursor: pointer;
	}
	.scrim {
		position: fixed;
		inset: 0;
		z-index: 200000;
		background: rgba(0, 0, 0, 0.4);
	}
	.modal {
		position: fixed;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		z-index: 200001;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
		gap: 12px;
	}
	.swatch {
		display: flex;
		flex-direction: column;
		gap: 6px;
		background: none;
		border: 1px solid transparent;
		border-radius: 10px;
		padding: 6px;
		cursor: pointer;
	}
	.swatch.active {
		border-color: var(--accent, #6ea8fe);
	}
	.preview {
		display: block;
		height: 72px;
		border-radius: 8px;
		border: 1px solid var(--glass-brd, rgba(255, 255, 255, 0.12));
		background: #222;
	}
	.name {
		font-size: 12px;
		color: var(--muted, #9aa4b2);
	}
	.muted {
		color: var(--muted, #9aa4b2);
	}
</style>
