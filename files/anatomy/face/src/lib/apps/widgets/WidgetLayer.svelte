<!--
  WidgetLayer — the desktop's widget host.

  A WIDGET IS NOT A WINDOW. It has no titlebar, no z-order, no snap cell and
  no entry in the window store, and it cannot be maximised or tiled. Since
  2026-11-08 (row face-widgets-movable-removable) it can be moved by its grip
  and hidden by its ✕; the palette shows it again. Prefs live in prefs.ts.

  It sits BELOW every window (z-index under the WM's range) and above the
  wallpaper, pinned to the bottom-left of the work area, out of the dock's way
  at the bottom-centre and out of the menubar's way at the top-right. The
  layer itself is pointer-transparent; each widget opts back in, so the empty
  desktop between widgets stays clickable.

  It renders `openableApps('widget')` (the viewer's tier, row face-app-min-tier) — the registry is the source of truth for
  which widgets exist, exactly as it is for dock apps. Each widget component
  resolves through the SAME lazy seam as a window body
  (`resolveNativeComponent`), so a widget is a first-class registered app and
  not a special case bolted onto the desktop root.

  Identity is handed down and each widget decides for itself whether it may
  render: what a widget shows is not uniformly public (the anatomy widget is
  Tier-1 operational internals), and pushing that decision into the layer
  would make the layer the arbiter of every widget's data policy.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { openableApps } from '$lib/apps/native';
	import WidgetHost from './WidgetHost.svelte';
	import { widgetPrefs, loadWidgetPrefs, setWidgetHidden, moveWidget } from './prefs';
	import type { Identity } from '$lib/contracts';

	let { identity }: { identity?: Identity } = $props();

	// Read once: the registry is populated on mount by
	// registerBuiltinNativeApps() before this layer renders, and widgets are
	// not added at runtime.
	const widgets = openableApps('widget');
	const shown = $derived(widgets.filter((w) => !$widgetPrefs.hidden.includes(w.slug)));

	// The grip drags; the widget body keeps its own clicks (no pointer capture: face-wm gotcha).
	let drag = $state<{ slug: string; dx: number; dy: number; x: number; y: number } | null>(null);

	function grab(e: PointerEvent, slug: string) {
		const box = (e.currentTarget as HTMLElement).closest('.slot')!.getBoundingClientRect();
		drag = { slug, dx: e.clientX - box.left, dy: e.clientY - box.top, x: box.left, y: box.top };
		e.preventDefault();
	}
	function follow(e: PointerEvent) {
		if (drag) drag = { ...drag, x: e.clientX - drag.dx, y: e.clientY - drag.dy };
	}
	function drop() {
		if (!drag) return;
		moveWidget(drag.slug, drag.x, drag.y, window.innerWidth, window.innerHeight);
		drag = null;
	}
	function at(slug: string): string {
		const p = drag?.slug === slug ? drag : $widgetPrefs.pos[slug];
		return p ? `position:fixed;left:${p.x}px;top:${p.y}px` : '';
	}

	onMount(() => {
		loadWidgetPrefs();
	});
</script>

<svelte:window onpointermove={follow} onpointerup={drop} />

{#if widgets.length > 0}
	<div class="widget-layer">
		{#each shown as w (w.slug)}
			<div class="slot" style={at(w.slug)}>
				<div class="tools">
					<button class="grip" aria-label="Move {w.title}" onpointerdown={(e) => grab(e, w.slug)}
						>⠿</button
					>
					<button
						class="hide"
						aria-label="Hide {w.title}"
						onclick={() => setWidgetHidden(w.slug, true)}>✕</button
					>
				</div>
				<WidgetHost slug={w.slug} {identity} />
			</div>
		{/each}
	</div>
{/if}

<style>
	.widget-layer {
		position: fixed;
		left: 16px;
		bottom: 96px; /* clear of the dock */
		display: grid;
		gap: 10px;
		z-index: 10; /* under every window, over the wallpaper */
		pointer-events: none; /* the desktop between widgets stays clickable */
	}
	.slot {
		position: relative;
		z-index: 10;
	}
	.tools {
		position: absolute;
		top: 4px;
		right: 4px;
		display: flex;
		gap: 2px;
		opacity: 0;
		transition: opacity 120ms;
		pointer-events: auto;
	}
	.slot:hover .tools,
	.slot:focus-within .tools {
		opacity: 1;
	}
	.tools button {
		border: 0;
		border-radius: 4px;
		padding: 0 5px;
		font-size: 12px;
		line-height: 18px;
		color: var(--fg);
		background: var(--glass);
		cursor: pointer;
	}
	.grip {
		cursor: grab;
		touch-action: none;
	}
</style>
