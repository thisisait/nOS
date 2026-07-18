<script lang="ts">
	import { onMount } from 'svelte';
	import { windows, openWindow, focusApp } from '$lib/stores/desktop';
	import Window from '$lib/components/Window.svelte';
	import NativeHost from '$lib/components/NativeHost.svelte';
	import Taskbar from '$lib/components/Taskbar.svelte';
	import TileDivider from '$lib/wm/TileDivider.svelte';
	import { applyTiling, clearTiling, tilingActive } from '$lib/wm/tiling';
	import CommandPalette, { type PaletteAction } from '$lib/palette/CommandPalette.svelte';
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
		getNativeApp,
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

	// Singleton launch: focus an already-open window for this app instead of
	// spawning an unbounded stack of duplicates (the "every link = new window" bug).
	function launchHub(app: HubApp) {
		if (!focusApp(app.slug)) openWindow({ app: app.slug, title: app.title, w: 720, h: 480 });
	}
	function launchNativeApp(slug: string) {
		if (!focusApp(slug)) launchNative(slug);
	}

	// Icon for a window's app slug (taskbar chips): native descriptor icon, else
	// the hub catalog icon, else the app's first letter.
	function iconFor(slug: string): string {
		return getNativeApp(slug)?.icon ?? apps.find((a) => a.slug === slug)?.icon ?? slug.slice(0, 1);
	}

	// Command-palette actions: launch every app + the built-in WM actions. Rebuilt
	// reactively as the hub catalog resolves.
	const paletteActions = $derived<PaletteAction[]>([
		...natives.map((a) => ({
			id: `native:${a.slug}`,
			title: a.title,
			hint: 'app',
			icon: a.icon,
			run: () => launchNativeApp(a.slug)
		})),
		...apps.map((a) => ({
			id: `hub:${a.slug}`,
			title: a.title,
			hint: 'service',
			icon: a.icon,
			run: () => launchHub(a)
		})),
		{
			id: 'act:control-panel',
			title: 'Control Panel',
			hint: 'system',
			icon: '⚙',
			run: () => openControlPanel()
		},
		{
			id: 'act:split',
			title: 'Tile: split side by side',
			hint: 'window',
			icon: '◨',
			run: () => applyTiling('half-v')
		},
		{
			id: 'act:thirds',
			title: 'Tile: three columns',
			hint: 'window',
			icon: '▦',
			run: () => applyTiling('thirds')
		},
		{
			id: 'act:grid',
			title: 'Tile: 2×2 grid',
			hint: 'window',
			icon: '⊞',
			run: () => applyTiling('2x2')
		},
		{ id: 'act:untile', title: 'Leave tiling', hint: 'window', icon: '◫', run: () => clearTiling() }
	]);
</script>

<div class="desktop" style={bg ? `background:${bg}` : ''}>
	<header class="menubar glass">
		<strong>nOS</strong>
		<button class="menu-item" onclick={() => openControlPanel()}>Control Panel</button>
		{#if $tilingActive}
			<button class="menu-item" onclick={() => clearTiling()} title="Leave tiling">◫ Untile</button>
		{:else}
			<button
				class="menu-item"
				onclick={() => applyTiling('half-v')}
				title="Two windows side by side">◨ Split</button
			>
			<button class="menu-item" onclick={() => applyTiling('thirds')} title="Three columns"
				>▦ Thirds</button
			>
			<button
				class="menu-item"
				onclick={() => applyTiling('2x2')}
				title="Four windows in a 2×2 grid">⊞ Grid</button
			>
		{/if}
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
				<NativeHost app={win.app} />
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
	<!-- Live split gutter (renders only while a split pair is active) -->
	<TileDivider />
	<!-- G5: file-picker host (invisible until openFilePicker / the bridge fires) -->
	<FilePicker />

	<!-- Open-window strip: count + navigation back to any window (Wave-2). -->
	<Taskbar icon={iconFor} />

	<!-- Ctrl+Space (hold 2s): launcher + actions + local-LLM ask. -->
	<CommandPalette actions={paletteActions} />

	<nav class="dock glass" aria-label="Dock">
		{#each natives as app (app.slug)}
			<button class="tile" title={app.title} onclick={() => launchNativeApp(app.slug)}>
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
