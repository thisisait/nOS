<!--
  TileDivider — the draggable gutters for the active grid tiling.

  Renders one vertical gutter per internal COLUMN boundary and one horizontal
  gutter per internal ROW boundary (so half-v has 1, thirds has 2, 2×2 has a
  cross of 2). Dragging a gutter re-allocates the two tracks it separates and
  re-tiles live; a viewport resize re-tiles so panes stay full and ratioed.
-->
<script lang="ts">
	import {
		tiling,
		prefix,
		setColumnBoundary,
		setRowBoundary,
		retile,
		MENUBAR
	} from '$lib/wm/tiling';

	let vw = $state(0);
	let vh = $state(0);
	let drag = $state<{ axis: 'col' | 'row'; i: number } | null>(null);

	const areaH = $derived(Math.max(0, vh - MENUBAR));
	// Internal boundary positions as cumulative fractions (drop the leading 0).
	const colBounds = $derived(prefix($tiling.cols).slice(1));
	const rowBounds = $derived(prefix($tiling.rows).slice(1));

	function down(axis: 'col' | 'row', i: number, e: PointerEvent) {
		drag = { axis, i };
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
		e.preventDefault();
	}
	function move(e: PointerEvent) {
		if (!drag) return;
		if (drag.axis === 'col') setColumnBoundary(drag.i, e.clientX / Math.max(1, vw));
		else setRowBoundary(drag.i, (e.clientY - MENUBAR) / Math.max(1, areaH));
	}
	function up() {
		drag = null;
	}

	// Re-tile on viewport resize so the grid tracks the new size.
	$effect(() => {
		void vw;
		void vh;
		retile();
	});
</script>

<svelte:window bind:innerWidth={vw} bind:innerHeight={vh} on:pointermove={move} on:pointerup={up} />

{#if $tiling.mode}
	{#each colBounds as b, i (i)}
		<div
			class="gutter v"
			class:dragging={drag?.axis === 'col' && drag?.i === i}
			style="left:{b * vw}px; top:{MENUBAR}px; height:{areaH}px;"
			onpointerdown={(e) => down('col', i, e)}
			role="separator"
			aria-label="Resize columns"
			aria-orientation="vertical"
			tabindex="-1"
		>
			<span class="grip"></span>
		</div>
	{/each}
	{#each rowBounds as b, i (i)}
		<div
			class="gutter h"
			class:dragging={drag?.axis === 'row' && drag?.i === i}
			style="top:{MENUBAR + b * areaH}px; left:0; width:{vw}px;"
			onpointerdown={(e) => down('row', i, e)}
			role="separator"
			aria-label="Resize rows"
			aria-orientation="horizontal"
			tabindex="-1"
		>
			<span class="grip"></span>
		</div>
	{/each}
{/if}

<style>
	.gutter {
		position: fixed;
		z-index: 90000;
		display: grid;
		place-items: center;
	}
	.gutter.v {
		width: 10px;
		margin-left: -5px;
		cursor: ew-resize;
	}
	.gutter.h {
		height: 10px;
		margin-top: -5px;
		cursor: ns-resize;
	}
	.grip {
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.28);
		transition: background 120ms ease-out;
	}
	.gutter.v .grip {
		width: 4px;
		height: 46px;
	}
	.gutter.h .grip {
		width: 46px;
		height: 4px;
	}
	.gutter:hover .grip,
	.gutter.dragging .grip {
		background: rgba(120, 180, 255, 0.9);
	}
</style>
