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
	import { loadTable } from '$lib/api/tables';
	import {
		activeWallpaper,
		setWallpaper,
		wallpapersFromTable,
		safeBackground,
		FALLBACK_WALLPAPERS
	} from '$lib/state/wallpaper';
	import type { WallpaperSpec } from '$lib/contracts';

	let choices = $state<WallpaperSpec[]>(FALLBACK_WALLPAPERS);

	onMount(async () => {
		try {
			const table = await loadTable('face-wallpapers');
			choices = wallpapersFromTable(table);
		} catch {
			choices = FALLBACK_WALLPAPERS;
		}
	});
</script>

<div class="picker">
	<p class="muted">Choose a desktop wallpaper.</p>
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

<style>
	.picker {
		display: flex;
		flex-direction: column;
		gap: 12px;
		font-size: 13px;
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
