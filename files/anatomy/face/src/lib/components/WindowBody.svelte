<!--
  WindowBody — what a window CONTAINS, independent of what frames it.

  Lifted out of the desktop root when mobile arrived: the four-way branch
  (control panel / component-backed app / iframe service / no launch URL) is
  the same answer whether the surface is a draggable window or a full-screen
  phone view. Two copies of it would drift the day a fifth form lands.
-->
<script lang="ts">
	import type { WindowModel } from '$lib/contracts';
	import NativeHost from './NativeHost.svelte';
	import ServiceFrame from './ServiceFrame.svelte';
	import { appForm } from '$lib/apps/native';
	import ControlPanelSurface from '$lib/apps/control-panel/ControlPanelSurface.svelte';
	import { isControlPanelWindow } from '$lib/apps/control-panel/surfaces';

	let { win }: { win: WindowModel } = $props();
</script>

{#if isControlPanelWindow(win.app)}
	<ControlPanelSurface {win} />
{:else if appForm(win.app) === 'view' || appForm(win.app) === 'utility'}
	<!-- The two component-backed window forms. `appForm` returns null for an
	     unregistered slug — a restored window whose hub entry has not arrived
	     yet falls through to its own url below, rather than being guessed into
	     the wrong renderer. -->
	<NativeHost app={win.app} />
{:else if win.url}
	<ServiceFrame url={win.url} title={win.title} embed={win.embed} />
{:else}
	<div class="placeholder">
		<p>{win.title}</p>
		<p class="muted">
			This service has no launch URL yet. It will open here once its catalog entry is wired.
		</p>
	</div>
{/if}

<style>
	.placeholder {
		display: grid;
		gap: 8px;
	}
	.muted {
		color: var(--muted);
	}
</style>
