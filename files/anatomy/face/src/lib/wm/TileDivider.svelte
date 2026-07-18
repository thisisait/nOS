<!--
  TileDivider — the draggable gutter between two split-tiled windows.

  Renders only while a split pair is active (see $lib/wm/split). Dragging it
  re-allocates the width ratio between the two panes live; window resize re-tiles
  so the split survives a viewport change (which also re-buckets the G4 cache).
-->
<script lang="ts">
	import { splitPair, splitRatio, setSplitRatio, retile, MENUBAR } from '$lib/wm/split';

	let vw = $state(0);
	let vh = $state(0);
	let dragging = $state(false);

	function down(e: PointerEvent) {
		dragging = true;
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
		e.preventDefault();
	}
	function move(e: PointerEvent) {
		if (dragging) setSplitRatio(e.clientX / Math.max(1, vw));
	}
	function up() {
		dragging = false;
	}

	// Re-tile on viewport resize so panes stay full-height + correctly ratioed.
	$effect(() => {
		void vw;
		void vh;
		retile();
	});
</script>

<svelte:window bind:innerWidth={vw} bind:innerHeight={vh} on:pointermove={move} on:pointerup={up} />

{#if $splitPair}
	<div
		class="divider"
		class:dragging
		style="left:{$splitRatio * vw}px; top:{MENUBAR}px; height:{Math.max(0, vh - MENUBAR)}px;"
		onpointerdown={down}
		role="separator"
		aria-label="Resize split"
		aria-orientation="vertical"
		tabindex="-1"
	>
		<span class="grip"></span>
	</div>
{/if}

<style>
	.divider {
		position: fixed;
		width: 10px;
		margin-left: -5px;
		z-index: 90000;
		cursor: ew-resize;
		display: grid;
		place-items: center;
	}
	.grip {
		width: 4px;
		height: 46px;
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.28);
		transition: background 120ms ease-out;
	}
	.divider:hover .grip,
	.divider.dragging .grip {
		background: rgba(120, 180, 255, 0.9);
	}
</style>
