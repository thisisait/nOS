<script lang="ts">
	import type { WindowModel } from '$lib/contracts';
	import {
		closeWindow,
		focusWindow,
		moveWindow,
		resizeWindow,
		toggleMin,
		toggleMax
	} from '$lib/stores/desktop';
	import type { Snippet } from 'svelte';
	import { beginWindowDrag, updateWindowDrag, endWindowDrag } from '$lib/wm/drag'; // G3

	let { win, children }: { win: WindowModel; children?: Snippet } = $props();

	let dragging = false;
	let resizing = false;
	let sx = 0;
	let sy = 0;
	let ox = 0;
	let oy = 0;
	let ow = 0;
	let oh = 0;

	function onTitlePointerDown(e: PointerEvent) {
		// Ignore presses that originate on a control (the traffic lights) — those
		// are `click` targets; starting a drag here would setPointerCapture on the
		// titlebar and steal the click. Belt-and-braces with stopPropagation below.
		if ((e.target as HTMLElement).closest('button')) return;
		if (win.max) return;
		dragging = true;
		sx = e.clientX;
		sy = e.clientY;
		ox = win.x;
		oy = win.y;
		focusWindow(win.id);
		beginWindowDrag(win.id, e.clientX, e.clientY); // G3: feed the snap overlay
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
	}
	function onGripPointerDown(e: PointerEvent) {
		resizing = true;
		sx = e.clientX;
		sy = e.clientY;
		ow = win.w;
		oh = win.h;
		focusWindow(win.id);
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
		e.stopPropagation();
	}
	function onPointerMove(e: PointerEvent) {
		if (dragging) {
			moveWindow(win.id, ox + (e.clientX - sx), Math.max(28, oy + (e.clientY - sy)));
			updateWindowDrag(e.clientX, e.clientY); // G3: drive the snap overlay
		} else if (resizing)
			resizeWindow(
				win.id,
				Math.max(240, ow + (e.clientX - sx)),
				Math.max(160, oh + (e.clientY - sy))
			);
	}
	function onPointerUp() {
		if (dragging) endWindowDrag(); // G3: resolve drop → maybe snap
		dragging = false;
		resizing = false;
	}
</script>

<svelte:window on:pointermove={onPointerMove} on:pointerup={onPointerUp} />

{#if !win.min}
	<!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
	<section
		class="win glass"
		style="left:{win.max ? 0 : win.x}px; top:{win.max ? 28 : win.y}px; width:{win.max
			? '100vw'
			: win.w + 'px'}; height:{win.max ? 'calc(100vh - 28px)' : win.h + 'px'}; z-index:{win.z};"
		onpointerdown={() => focusWindow(win.id)}
		role="dialog"
		aria-label={win.title}
		tabindex="-1"
		data-win-id={win.id}
	>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<header class="titlebar" onpointerdown={onTitlePointerDown}>
			<div class="lights">
				<button
					class="light close"
					aria-label="Close"
					onpointerdown={(e) => e.stopPropagation()}
					onclick={() => closeWindow(win.id)}
				></button>
				<button
					class="light min"
					aria-label="Minimize"
					onpointerdown={(e) => e.stopPropagation()}
					onclick={() => toggleMin(win.id)}
				></button>
				<button
					class="light max"
					aria-label="Maximize"
					onpointerdown={(e) => e.stopPropagation()}
					onclick={() => toggleMax(win.id)}
				></button>
			</div>
			<span class="title">{win.title}</span>
		</header>
		<div class="body">
			{#if children}{@render children()}{/if}
		</div>
		{#if !win.max}
			<div class="grip" onpointerdown={onGripPointerDown} role="presentation"></div>
		{/if}
	</section>
{/if}

<style>
	.win {
		position: fixed;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		box-shadow: 0 18px 50px rgba(0, 0, 0, 0.5);
		min-width: 240px;
		min-height: 160px;
	}
	.titlebar {
		height: 34px;
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 0 12px;
		cursor: grab;
		user-select: none;
		border-bottom: 1px solid var(--glass-brd);
	}
	.lights {
		display: flex;
		gap: 7px;
	}
	.light {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		border: none;
		padding: 0;
	}
	.close {
		background: #ff5f57;
	}
	.min {
		background: #febc2e;
	}
	.max {
		background: #28c840;
	}
	.title {
		font-size: 13px;
		color: var(--muted);
	}
	.body {
		flex: 1;
		overflow: auto;
		padding: 12px;
	}
	.grip {
		position: absolute;
		right: 0;
		bottom: 0;
		width: 16px;
		height: 16px;
		cursor: nwse-resize;
	}
</style>
