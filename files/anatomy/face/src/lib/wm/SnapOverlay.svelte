<!--
  WM v2 · SnapOverlay (Wave-1 G3).

  Mount ONE <SnapOverlay /> in the desktop (see +page.svelte INTEGRATION NOTE).
  It observes the shared drag state (`$lib/wm/drag`) that the window titlebar
  feeds, and renders the snap affordance:

    • while a window is dragged, a dropzone pill sits at the top edge;
    • when the pointer reaches the top trigger band, it GROWS and reveals the
      active layout's CELLS as translucent drop targets across the work area;
    • the cell under the pointer highlights;
    • on drop (drag end) into a cell it calls `snapWindow(...)` → tiled mode.

  The overlay is purely visual (`pointer-events: none`) — the window keeps its
  pointer capture during the drag, and hover/drop are resolved from the drag
  coordinates, not DOM hover. No snap logic lives in Window.svelte.
-->
<script lang="ts">
	import { dragState } from '$lib/wm/drag';
	import { activeLayout } from '$lib/wm/layouts';
	import { snapEngine, cellAt } from '$lib/wm/snap-engine';
	import { snapWindow } from '$lib/stores/desktop';

	/** Height of the desktop menubar; the work area starts below it. */
	let { menubar = 28, trigger = 72 }: { menubar?: number; trigger?: number } = $props();

	let vw = $state(0);
	let vh = $state(0);

	const area = $derived({ w: vw, h: Math.max(0, vh - menubar) });
	const cells = $derived(snapEngine.cells($activeLayout, area));

	// Rendering state.
	let revealed = $state(false); // dropzone grown → cell grid shown
	let hovered = $state<string | null>(null); // cell under the pointer

	// Non-reactive drag bookkeeping (avoids effect self-dependency loops).
	let sticky = false; // stayed-revealed for the rest of this drag
	let wasActive = false;

	$effect(() => {
		const s = $dragState;
		const layout = $activeLayout;
		const a = { w: vw, h: Math.max(0, vh - menubar) };
		const relY = s.y - menubar;

		if (s.active) {
			wasActive = true;
			if (relY < trigger) {
				sticky = true;
				revealed = true;
			}
			hovered = sticky ? cellAt(snapEngine.cells(layout, a), { x: s.x, y: relY }) : null;
		} else {
			if (wasActive) {
				wasActive = false;
				// Falling edge: dragState still holds windowId + last pointer.
				if (sticky && s.windowId) {
					const cid = cellAt(snapEngine.cells(layout, a), { x: s.x, y: relY });
					if (cid) snapWindow(s.windowId, layout, cid, a);
				}
			}
			sticky = false;
			revealed = false;
			hovered = null;
		}
	});
</script>

<svelte:window bind:innerWidth={vw} bind:innerHeight={vh} />

{#if $dragState.active}
	<div class="snap-overlay" style="top:{menubar}px" aria-hidden="true">
		{#if revealed}
			<!-- Grown dropzone: the active layout's cells as drop targets. -->
			<div class="cells">
				{#each cells as c (c.id)}
					<div
						class="cell"
						class:hot={hovered === c.id}
						style="left:{c.x}px; top:{c.y}px; width:{c.w}px; height:{c.h}px;"
					></div>
				{/each}
			</div>
			<div class="hint pinned">Drop into a cell · {$activeLayout.name}</div>
		{:else}
			<!-- Collapsed dropzone pill; move to the top edge to reveal cells. -->
			<div class="pill">Snap · drag to top</div>
		{/if}
	</div>
{/if}

<style>
	.snap-overlay {
		position: fixed;
		left: 0;
		right: 0;
		bottom: 0;
		pointer-events: none;
		z-index: 100000;
	}
	.pill {
		position: absolute;
		top: 8px;
		left: 50%;
		transform: translateX(-50%);
		padding: 6px 14px;
		border-radius: 999px;
		font-size: 12px;
		color: #fff;
		background: rgba(40, 120, 255, 0.55);
		box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
		backdrop-filter: blur(6px);
		animation: grow 160ms ease-out;
	}
	.cells {
		position: absolute;
		inset: 0;
	}
	.cell {
		position: absolute;
		border: 2px dashed rgba(255, 255, 255, 0.35);
		border-radius: 12px;
		background: rgba(40, 120, 255, 0.1);
		transition:
			background 90ms ease-out,
			border-color 90ms ease-out;
	}
	.cell.hot {
		background: rgba(40, 120, 255, 0.38);
		border-color: rgba(120, 180, 255, 0.95);
		border-style: solid;
	}
	.hint {
		position: absolute;
		left: 50%;
		transform: translateX(-50%);
		padding: 5px 12px;
		border-radius: 999px;
		font-size: 12px;
		color: #fff;
		background: rgba(0, 0, 0, 0.45);
	}
	.hint.pinned {
		top: 10px;
	}
	@keyframes grow {
		from {
			opacity: 0;
			transform: translateX(-50%) scale(0.85);
		}
		to {
			opacity: 1;
			transform: translateX(-50%) scale(1);
		}
	}
</style>
