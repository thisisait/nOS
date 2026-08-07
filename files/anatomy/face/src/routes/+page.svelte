<script lang="ts">
	import { onMount } from 'svelte';
	import { windows, openWindow, focusApp } from '$lib/stores/desktop';
	import Window from '$lib/components/Window.svelte';
	import NativeHost from '$lib/components/NativeHost.svelte';
	import ServiceFrame from '$lib/components/ServiceFrame.svelte';
	import Dock, { type DockApp } from '$lib/components/Dock.svelte';
	import TileDivider from '$lib/wm/TileDivider.svelte';
	import { applyTiling, clearTiling } from '$lib/wm/tiling';
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
	import { isControlPanelWindow, CP_GRID_APP } from '$lib/apps/control-panel/surfaces'; // G4
	import {
		registerBuiltinNativeApps,
		registerHubFrames,
		appsOfForm,
		launchNative,
		appForm,
		initFilePickerBridge
	} from '$lib/apps/native'; // G5
	import FilePicker from '$lib/apps/native/file-picker/FilePicker.svelte'; // G5
	import WidgetLayer from '$lib/apps/widgets/WidgetLayer.svelte';
	import MenubarStatus from '$lib/components/MenubarStatus.svelte';
	import Clock from '$lib/components/Clock.svelte';
	import { initShortcuts, SHORTCUTS, run as runShortcut } from '$lib/wm/shortcuts';
	import { requestAnatomy, type AnatomyView } from '$lib/anatomy/focus';

	let { data }: { data: PageData } = $props();
	let apps = $state<HubApp[]>([]);
	registerBuiltinNativeApps();
	// Dock + palette tiles: the two forms that OPEN A WINDOW. A widget is
	// mounted by <WidgetLayer /> and a frame is launched from the hub catalog
	// below, so neither belongs in this list.
	const natives = appsOfForm('view', 'utility');

	// Reactive desktop background from the active wallpaper (validated).
	const bg = $derived(safeBackground($activeWallpaper));

	onMount(() => {
		initWindowManager(); // G3: register SnapEngine + load face-layouts
		initWallpaper(); // G4: restore saved wallpaper
		initWindowCache(); // G4: usePersistence + restore geometry for this viewport
		// G5: postMessage file-picker bridge (origin allowlist hardened in G6/G7).
		const stopBridge = initFilePickerBridge({ allowedOrigins: [] });
		// Window keyboard control. Bindings avoid the browser's own (Cmd+W is
		// tab-close) and bail inside text fields — see wm/shortcuts.ts.
		const stopKeys = initShortcuts();

		void (async () => {
			try {
				apps = await hubApps();
				// Record the catalog on the `form` axis. A hub entry's form is
				// `frame` because THIS FILE renders it through <ServiceFrame />
				// below — the fact belongs beside the render path, not in the
				// catalog, which declares nothing of the sort.
				registerHubFrames(apps);
			} catch {
				apps = [];
			}
		})();

		return () => {
			stopBridge?.();
			stopKeys();
		};
	});

	/** Menubar chip → open Anatomy on the view that answers it. */
	function openAnatomy(view: AnatomyView) {
		requestAnatomy(view);
		launchNativeApp('anatomy');
	}

	// Singleton launch: focus an already-open window for this app instead of
	// spawning an unbounded stack of duplicates (the "every link = new window" bug).
	function launchHub(app: HubApp) {
		if (!focusApp(app.slug))
			openWindow({
				app: app.slug,
				title: app.title,
				w: 720,
				h: 480,
				url: app.url,
				embed: app.embed
			});
	}
	function launchNativeApp(slug: string) {
		if (!focusApp(slug)) launchNative(slug);
	}

	// Unified dock: native apps + Control Panel + hub services, in one strip. Each
	// entry carries how to launch it; the Dock adds the running-count badge +
	// hover window-switcher. Rebuilt reactively as the hub catalog resolves.
	const dockApps = $derived<DockApp[]>([
		...natives.map((a) => ({
			key: a.slug,
			title: a.title,
			icon: a.icon,
			launch: () => launchNativeApp(a.slug)
		})),
		{
			key: CP_GRID_APP,
			title: 'Control Panel',
			icon: '⚙️',
			isControlPanel: true,
			launch: openControlPanel
		},
		...apps.map((a) => ({ key: a.slug, title: a.title, icon: a.icon, launch: () => launchHub(a) }))
	]);

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
		{ id: 'act:untile', title: 'Leave tiling', hint: 'window', icon: '◫', run: () => clearTiling() },
		// The shortcuts are discoverable here rather than only in a source file.
		// Selecting one performs it, so the palette doubles as the help sheet.
		...SHORTCUTS.map((s, i) => ({
			id: `key:${i}`,
			title: s.what,
			hint: s.chord,
			icon: '⌨',
			run: () => void runShortcut(s.action)
		}))
	]);
</script>

<div class="desktop" style={bg ? `background:${bg}` : ''}>
	<!-- macOS-style menubar: transparent + all content right-aligned + click-through
	     (pointer-events:none) so a maximized/top-snapped window's titlebar + its
	     top-LEFT controls stay visible AND draggable underneath the bar. -->
	<header class="menubar">
		<strong>nOS</strong>
		<span class="spacer"></span>
		<!-- Ambient system awareness. Tier-1 only; everyone else sees nothing,
		     which is deliberate — job failures are operator information. -->
		<MenubarStatus onopen={openAnatomy} />
		{#if data.identity.authenticated}
			<span class="user">{data.identity.username}</span>
		{:else}
			<span class="user muted">not signed in</span>
		{/if}
		<Clock />
	</header>

	{#each $windows as win (win.id)}
		<Window {win}>
			{#if isControlPanelWindow(win.app)}
				<ControlPanelSurface {win} />
			{:else if appForm(win.app) === 'view' || appForm(win.app) === 'utility'}
				<!-- The two component-backed window forms. `appForm` returns null
				     for an unregistered slug — a restored window whose hub entry
				     has not arrived yet falls through to its own url below,
				     rather than being guessed into the wrong renderer. -->
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
		</Window>
	{/each}

	<!-- G3: snap/tiling overlay (renders only while a window is dragged) -->
	<SnapOverlay />
	<!-- Live split gutter (renders only while a split pair is active) -->
	<TileDivider />
	<!-- G5: file-picker host (invisible until openFilePicker / the bridge fires) -->
	<FilePicker />

	<!-- Desktop widgets (form=widget): small surfaces that are not windows. -->
	<WidgetLayer identity={data.identity} />

	<!-- Ctrl+Space (hold 2s): launcher + actions + local-LLM ask. -->
	<CommandPalette actions={paletteActions} />

	<!-- Unified dock: every app + running badges + hover window-switcher. -->
	<Dock apps={dockApps} />
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
		gap: 12px;
		padding: 0 14px;
		font-size: 13px;
		z-index: 100000;
		background: transparent; /* macOS-style: no fill */
		pointer-events: none; /* click-through — window titlebars underneath stay live */
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
	.placeholder {
		display: grid;
		gap: 8px;
	}
</style>
