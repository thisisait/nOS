<script lang="ts">
	import { onMount } from 'svelte';
	import { windows, openWindow } from '$lib/stores/desktop';
	import Window from '$lib/components/Window.svelte';
	import { hubApps } from '$lib/api/hub';
	import type { HubApp } from '$lib/contracts';
	import type { PageData } from './$types';

	// Wave-1 features wired at the desktop root.
	import { initWindowManager } from '$lib/wm/init'; // G3
	import SnapOverlay from '$lib/wm/SnapOverlay.svelte'; // G3
	import { initWindowCache } from '$lib/state/window-cache'; // G4
	import { initWallpaper, activeWallpaper, safeBackground } from '$lib/state/wallpaper'; // G4
	import { openControlPanel } from '$lib/apps/control-panel/ControlPanel.svelte'; // G4
	import ControlPanelSurface from '$lib/apps/control-panel/ControlPanelSurface.svelte'; // G4
	import { isControlPanelWindow } from '$lib/apps/control-panel/surfaces'; // G4
	import {
		registerBuiltinNativeApps,
		nativeApps,
		launchNative,
		isNativeApp,
		resolveNativeComponent,
		initFilePickerBridge
	} from '$lib/apps/native'; // G5
	import FilePicker from '$lib/apps/native/file-picker/FilePicker.svelte'; // G5

	let { data }: { data: PageData } = $props();
	let apps = $state<HubApp[]>([]);
	registerBuiltinNativeApps();
	const natives = nativeApps();

	// Reactive desktop background from the active wallpaper (validated).
	const bg = $derived(safeBackground($activeWallpaper));

	onMount(() => {
		initWindowManager(); // G3: register SnapEngine + load face.layouts
		initWallpaper(); // G4: restore saved wallpaper
		initWindowCache(); // G4: usePersistence + restore geometry for this viewport
		// G5: postMessage file-picker bridge (origin allowlist hardened in G6/G7).
		const stopBridge = initFilePickerBridge({ allowedOrigins: [] });

		void (async () => {
			try {
				apps = await hubApps();
			} catch {
				apps = [];
			}
		})();

		return () => stopBridge?.();
	});

	function launchHub(app: HubApp) {
		openWindow({ app: app.slug, title: app.title, w: 720, h: 480 });
	}
</script>

<div class="desktop" style={bg ? `background:${bg}` : ''}>
	<header class="menubar glass">
		<strong>nOS</strong>
		<button class="menu-item" onclick={() => openControlPanel()}>Control Panel</button>
		<span class="spacer"></span>
		{#if data.identity.authenticated}
			<span class="user">{data.identity.username}</span>
		{:else}
			<span class="user muted">not signed in</span>
		{/if}
	</header>

	{#each $windows as win (win.id)}
		<Window {win}>
			{#if isControlPanelWindow(win.app)}
				<ControlPanelSurface {win} />
			{:else if isNativeApp(win.app)}
				{#await resolveNativeComponent(win.app) then Comp}
					{#if Comp}<Comp />{/if}
				{/await}
			{:else}
				<div class="placeholder">
					<p>{win.title}</p>
					<p class="muted">
						This service opens as a native window. iframe embedding is used only for services that
						support it.
					</p>
				</div>
			{/if}
		</Window>
	{/each}

	<!-- G3: snap/tiling overlay (renders only while a window is dragged) -->
	<SnapOverlay />
	<!-- G5: file-picker host (invisible until openFilePicker / the bridge fires) -->
	<FilePicker />

	<nav class="dock glass" aria-label="Dock">
		{#each natives as app (app.slug)}
			<button class="tile" title={app.title} onclick={() => launchNative(app.slug)}>
				<span class="ico">{app.icon.slice(0, 2)}</span>
				<span class="lbl">{app.title}</span>
			</button>
		{/each}
		{#each apps as app (app.slug)}
			<button class="tile" title={app.description} onclick={() => launchHub(app)}>
				<span class="ico">{app.icon.slice(0, 2)}</span>
				<span class="lbl">{app.title}</span>
			</button>
		{/each}
		{#if natives.length === 0 && apps.length === 0}
			<span class="muted">no apps in catalog</span>
		{/if}
	</nav>
</div>

<style>
	.desktop {
		position: fixed;
		inset: 0;
		background: radial-gradient(1200px 800px at 30% 20%, #16203a, #0b0d12 60%);
	}
	.menubar {
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		height: 28px;
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 0 14px;
		border-radius: 0;
		font-size: 13px;
		z-index: 100000;
	}
	.menu-item {
		background: none;
		border: none;
		color: var(--muted);
		padding: 2px 6px;
		border-radius: 6px;
		font-size: 13px;
	}
	.menu-item:hover {
		color: var(--fg);
		background: rgba(255, 255, 255, 0.08);
	}
	.spacer {
		flex: 1;
	}
	.user {
		color: var(--fg);
	}
	.muted {
		color: var(--muted);
	}
	.dock {
		position: fixed;
		bottom: 14px;
		left: 50%;
		transform: translateX(-50%);
		display: flex;
		gap: 10px;
		padding: 10px 14px;
		align-items: flex-end;
		max-width: 90vw;
		overflow-x: auto;
		z-index: 100000;
	}
	.tile {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		background: none;
		border: none;
		width: 64px;
	}
	.ico {
		width: 44px;
		height: 44px;
		display: grid;
		place-items: center;
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.08);
		font-size: 13px;
		text-transform: uppercase;
	}
	.lbl {
		font-size: 11px;
		color: var(--muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 64px;
	}
	.placeholder {
		display: grid;
		gap: 8px;
	}
</style>
