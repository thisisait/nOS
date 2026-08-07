<!--
  WidgetLayer — the desktop's widget host.

  A WIDGET IS NOT A WINDOW. It has no titlebar, no z-order, no snap cell and
  no entry in the window store; it is not draggable and it cannot be
  minimised. That is the whole distinction `form: 'widget'` records, and it is
  why this layer exists instead of the window manager doing the job: giving a
  widget a Window would give it every affordance a window has, and a widget
  that can be closed, maximised and tiled is a small window, not a widget.

  It sits BELOW every window (z-index under the WM's range) and above the
  wallpaper, pinned to the bottom-left of the work area, out of the dock's way
  at the bottom-centre and out of the menubar's way at the top-right. The
  layer itself is pointer-transparent; each widget opts back in, so the empty
  desktop between widgets stays clickable.

  It renders `appsOfForm('widget')` — the registry is the source of truth for
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
	import { appsOfForm } from '$lib/apps/native';
	import WidgetHost from './WidgetHost.svelte';
	import type { Identity } from '$lib/contracts';

	let { identity }: { identity?: Identity } = $props();

	// Read once: the registry is populated on mount by
	// registerBuiltinNativeApps() before this layer renders, and widgets are
	// not added at runtime.
	const widgets = appsOfForm('widget');
</script>

{#if widgets.length > 0}
	<div class="widget-layer">
		{#each widgets as w (w.slug)}
			<WidgetHost slug={w.slug} {identity} />
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
</style>
