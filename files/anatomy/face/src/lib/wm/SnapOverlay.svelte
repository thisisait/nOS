<!--
  WM v2 · SnapOverlay — drag-to-top LAYOUT PICKER.

  Mount ONE <SnapOverlay /> in the desktop. It observes the shared drag state
  (`$lib/wm/drag`) the window titlebar feeds and renders the snap affordance:

    • while a window is dragged, a hint pill sits at the top;
    • when the pointer reaches the top trigger band, a LAYOUT PICKER appears —
      a row of layout previews (single / halves / thirds / 2×2);
    • dragging the pointer OVER a preview ARMS that layout (its cells appear as
      translucent drop targets across the work area);
    • the cell under the pointer highlights; releasing over it snaps the window
      into that cell of the armed layout.

  Everything is coordinate-driven, NOT DOM hover: the dragged window holds the
  pointer capture, so the overlay stays `pointer-events: none` and resolves the
  armed layout + hovered cell purely from the drag (x,y). No snap logic in
  Window.svelte; drag.ts is unchanged.
-->
<script lang="ts">
	import { dragState } from '$lib/wm/drag';
	import { BUILTIN_LAYOUTS } from '$lib/wm/layouts';
	import { snapEngine, cellAt } from '$lib/wm/snap-engine';
	import { snapWindow } from '$lib/stores/desktop';
	import type { LayoutSpec } from '$lib/contracts';

	/** Height of the desktop menubar; the work area starts below it. */
	let { menubar = 28, trigger = 90 }: { menubar?: number; trigger?: number } = $props();

	// The pickable layouts (the built-in set, in a stable order).
	const PICK: LayoutSpec[] = ['single', 'half-v', 'half-h', 'thirds', '2x2']
		.map((s) => BUILTIN_LAYOUTS.find((l) => l.slug === s))
		.filter((l): l is LayoutSpec => l !== undefined);

	// Picker option geometry (relative to the work-area top-left; x == viewport x
	// because the overlay spans the full width at left:0).
	const OPT_W = 74;
	const OPT_H = 56;
	const GAP = 10;
	const PICK_TOP = 12;
	const PICK_BAND = PICK_TOP + OPT_H + 10; // below this band, target cells

	let vw = $state(0);
	let vh = $state(0);

	const area = $derived({ w: vw, h: Math.max(0, vh - menubar) });

	/** Picker option rects (viewport x, work-area-relative y). */
	const optRects = $derived.by(() => {
		const total = PICK.length * OPT_W + (PICK.length - 1) * GAP;
		const startX = Math.max(8, (vw - total) / 2);
		return PICK.map((layout, i) => ({
			layout,
			x: startX + i * (OPT_W + GAP),
			y: PICK_TOP,
			w: OPT_W,
			h: OPT_H
		}));
	});

	// Reactive render state.
	let revealed = $state(false);
	let armedSlug = $state('single');
	let hovered = $state<string | null>(null);

	// Non-reactive bookkeeping (avoids effect self-dependency loops).
	let stickyRevealed = false;
	let armed = 'single';
	let wasActive = false;

	function layoutFor(slug: string): LayoutSpec {
		return PICK.find((l) => l.slug === slug) ?? PICK[0] ?? BUILTIN_LAYOUTS[0];
	}

	/** Cells of the currently-armed layout, for rendering the drop targets. */
	const armedCells = $derived(snapEngine.cells(layoutFor(armedSlug), area));

	$effect(() => {
		const s = $dragState;
		const rects = optRects;
		const a = { w: vw, h: Math.max(0, vh - menubar) };
		const relY = s.y - menubar;

		if (s.active) {
			wasActive = true;
			if (relY < trigger) stickyRevealed = true;

			let hov: string | null = null;
			if (stickyRevealed) {
				if (relY >= PICK_TOP && relY <= PICK_TOP + OPT_H) {
					// In the picker strip → arm the layout under the pointer.
					const hit = rects.find((r) => s.x >= r.x && s.x <= r.x + r.w);
					if (hit) armed = hit.layout.slug;
				} else if (relY >= PICK_BAND) {
					// Below the strip → highlight the target cell of the armed layout.
					hov = cellAt(snapEngine.cells(layoutFor(armed), a), { x: s.x, y: relY });
				}
			}
			revealed = stickyRevealed;
			armedSlug = armed;
			hovered = hov;
		} else {
			if (wasActive) {
				wasActive = false;
				// Falling edge: commit the snap if released over a cell (recomputed
				// from the last pointer, never read from the reactive `hovered`).
				if (stickyRevealed && s.windowId && relY >= PICK_BAND) {
					const layout = layoutFor(armed);
					const cid = cellAt(snapEngine.cells(layout, a), { x: s.x, y: relY });
					if (cid) snapWindow(s.windowId, layout, cid, a);
				}
			}
			stickyRevealed = false;
			armed = 'single';
			revealed = false;
			armedSlug = 'single';
			hovered = null;
		}
	});
</script>

<svelte:window bind:innerWidth={vw} bind:innerHeight={vh} />

{#if $dragState.active}
	<div class="snap-overlay" style="top:{menubar}px" aria-hidden="true">
		{#if revealed}
			<!-- Armed layout's cells as drop targets. -->
			<div class="cells">
				{#each armedCells as c (c.id)}
					<div
						class="cell"
						class:hot={hovered === c.id}
						style="left:{c.x}px; top:{c.y}px; width:{c.w}px; height:{c.h}px;"
					></div>
				{/each}
			</div>

			<!-- Layout picker row: drag over a preview to arm it. -->
			<div class="picker">
				{#each optRects as r (r.layout.slug)}
					<div
						class="opt"
						class:armed={armedSlug === r.layout.slug}
						style="left:{r.x}px; top:{r.y}px; width:{r.w}px; height:{r.h}px;"
					>
						<div class="mini">
							{#each r.layout.cells as cell (cell.id)}
								<span
									style="left:{cell.x * 100}%; top:{cell.y * 100}%; width:{cell.w *
										100}%; height:{cell.h * 100}%;"
								></span>
							{/each}
						</div>
						<span class="opt-lbl">{r.layout.name}</span>
					</div>
				{/each}
			</div>
		{:else}
			<div class="pill">Snap · drag to the top to tile</div>
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
		top: 10px;
		left: 50%;
		transform: translateX(-50%);
		padding: 6px 14px;
		border-radius: 999px;
		font-size: 12px;
		color: #fff;
		background: rgba(40, 120, 255, 0.55);
		box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
		backdrop-filter: blur(6px);
	}
	.cells {
		position: absolute;
		inset: 0;
	}
	.cell {
		position: absolute;
		border: 2px dashed rgba(255, 255, 255, 0.3);
		border-radius: 12px;
		background: rgba(40, 120, 255, 0.08);
		transition:
			background 90ms ease-out,
			border-color 90ms ease-out;
	}
	.cell.hot {
		background: rgba(40, 120, 255, 0.4);
		border-color: rgba(120, 180, 255, 0.95);
		border-style: solid;
	}
	.picker {
		position: absolute;
		inset: 0;
	}
	.opt {
		position: absolute;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		padding: 6px;
		border-radius: 10px;
		background: rgba(20, 24, 40, 0.82);
		border: 1px solid rgba(255, 255, 255, 0.14);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
		box-sizing: border-box;
		transition:
			border-color 90ms ease-out,
			transform 90ms ease-out;
	}
	.opt.armed {
		border-color: rgba(120, 180, 255, 0.95);
		transform: translateY(2px) scale(1.04);
	}
	.mini {
		position: relative;
		width: 100%;
		flex: 1;
		border-radius: 4px;
		background: rgba(255, 255, 255, 0.05);
		overflow: hidden;
	}
	.mini span {
		position: absolute;
		background: rgba(120, 180, 255, 0.55);
		border: 1px solid rgba(20, 24, 40, 0.9);
		box-sizing: border-box;
		border-radius: 2px;
	}
	.opt.armed .mini span {
		background: rgba(120, 180, 255, 0.9);
	}
	.opt-lbl {
		font-size: 10px;
		line-height: 1;
		color: #cfd8e6;
		white-space: nowrap;
	}
</style>
