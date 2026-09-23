<!--
  MobileShell — the face on a phone. NOT a shrunken desktop.

  A desktop metaphor does not survive 390px: dragging a window with a thumb,
  a hover window-switcher and two overlapping windows are all mouse-and-space
  affordances. So this mode does not offer them. What it keeps is the part
  that actually is the face — the apps — and it shows exactly one of them at
  a time, full-screen.

  IT ADDS NO STATE. The front-most window in the shared desktop store IS the
  visible app (`frontWindow`), the bottom bar is `splitDock` over the SAME
  `pinned.ts` pin order the dock uses, and launching goes through the same
  `DockApp.launch` the dock calls. Rotate a phone into landscape past the
  breakpoint and the windows are already there, sized and stacked.

  Home is the app list: every app in the catalog, running ones marked. That
  is why there is no separate Launchpad overlay here — the overlay's job on
  the desktop (show what the 14 pinned slots cannot) has no scarcity to solve
  when the whole screen is the list.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { windows, focusWindow, closeWindow } from '$lib/stores/desktop';
	import { isControlPanelWindow } from '$lib/apps/control-panel/surfaces';
	import { splitDock, loadPinned, pinnedSlugs, MOBILE_DOCK_SLOTS } from '$lib/apps/pinned';
	import { frontWindow } from '$lib/layout/mode';
	import WindowBody from './WindowBody.svelte';
	import Icon from './ui/Icon.svelte';
	import type { DockApp } from './Dock.svelte';
	import type { Identity } from '$lib/contracts';

	let { apps = [], identity }: { apps?: DockApp[]; identity?: Identity } = $props();

	// Home is a request, not a place: it holds only until an app is opened, and
	// a closed last window falls back to it because `front` goes null.
	let home = $state(true);
	const front = $derived(frontWindow($windows));
	const showing = $derived(home ? null : front);
	const bar = $derived(splitDock(apps, $pinnedSlugs, MOBILE_DOCK_SLOTS).bar);

	onMount(() => void loadPinned());

	function winsFor(app: DockApp) {
		return $windows.filter((w) =>
			app.isControlPanel ? isControlPanelWindow(w.app) : w.app === app.key
		);
	}

	function open(app: DockApp) {
		const wins = winsFor(app);
		if (wins.length === 0) app.launch();
		else focusWindow([...wins].sort((a, b) => b.z - a.z)[0].id);
		home = false;
	}
</script>

<div class="mshell">
	{#if showing}
		<header class="topbar">
			<button class="key" onclick={() => (home = true)} aria-label="All apps">☰</button>
			<span class="ttl">{showing.title}</span>
			<button class="key" onclick={() => closeWindow(showing.id)} aria-label="Close {showing.title}"
				>✕</button
			>
		</header>
		<main class="surface" data-win-id={showing.id}>
			<WindowBody win={showing} />
		</main>
	{:else}
		<header class="topbar">
			<strong>nOS</strong>
			<span class="ttl"></span>
			<span class="user" class:muted={!identity?.authenticated}>
				{identity?.authenticated ? identity.username : 'not signed in'}
			</span>
		</header>
		<main class="surface home">
			{#if apps.length === 0}
				<p class="muted">No apps in catalog.</p>
			{:else}
				<div class="grid">
					{#each apps as app (app.key)}
						{@const n = winsFor(app).length}
						<button class="cell" onclick={() => open(app)}>
							<span class="ico">
								<Icon icon={app.icon} title={app.title} size={28} labelled={false} />
								{#if n > 0}<span class="badge">{n}</span>{/if}
							</span>
							<span class="cell-lbl">{app.title}</span>
						</button>
					{/each}
				</div>
			{/if}
		</main>
	{/if}

	<nav class="bottombar" aria-label="App switcher">
		<button class="tile" class:on={home} onclick={() => (home = true)} aria-label="Home">
			<span class="ico"><Icon icon="▦" title="Home" size={22} labelled={false} /></span>
		</button>
		{#each bar as app (app.key)}
			{@const n = winsFor(app).length}
			<button
				class="tile"
				class:on={!home && showing?.app === app.key}
				onclick={() => open(app)}
				aria-label={app.title}
			>
				<span class="ico">
					<Icon icon={app.icon} title={app.title} size={22} labelled={false} />
					{#if n > 0}<span class="run"></span>{/if}
				</span>
			</button>
		{/each}
	</nav>
</div>

<style>
	.mshell {
		position: fixed;
		inset: 0;
		display: flex;
		flex-direction: column;
		/* The notch and the home indicator are not ours to draw on. */
		padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom)
			env(safe-area-inset-left);
	}
	.topbar {
		flex: 0 0 auto;
		display: flex;
		align-items: center;
		gap: 8px;
		height: 44px;
		padding: 0 6px;
		font-size: 14px;
		border-bottom: 1px solid var(--glass-brd);
	}
	.ttl {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--muted);
	}
	.user {
		font-size: 12px;
		padding-right: 6px;
	}
	.key {
		flex: none;
		width: 44px;
		height: 44px;
		border: none;
		background: none;
		color: var(--fg);
		font-size: 15px;
	}
	.surface {
		flex: 1 1 auto;
		min-height: 0;
		/* Wide content scrolls HERE (and inside its own component), never the
		   document — html/body are overflow:hidden. */
		overflow: auto;
		padding: 10px;
	}
	.home {
		padding: 14px 12px;
	}
	.grid {
		display: grid;
		/* min() so a 4-inch phone gets one column instead of a horizontal
		   scrollbar; auto-fill fans out as soon as there is room. */
		grid-template-columns: repeat(auto-fill, minmax(min(104px, 100%), 1fr));
		gap: 12px;
	}
	.cell {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 7px;
		min-height: 88px;
		padding: 12px 6px;
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid var(--glass-brd);
		border-radius: 14px;
		color: var(--fg);
	}
	.cell-lbl {
		font-size: 12px;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.bottombar {
		flex: 0 0 auto;
		display: flex;
		justify-content: space-around;
		align-items: center;
		gap: 4px;
		padding: 6px 8px;
		border-top: 1px solid var(--glass-brd);
		background: var(--glass);
		backdrop-filter: blur(18px) saturate(140%);
		-webkit-backdrop-filter: blur(18px) saturate(140%);
	}
	.tile {
		/* 48px ≥ the 44px minimum touch target. */
		width: 48px;
		height: 48px;
		display: grid;
		place-items: center;
		border: none;
		border-radius: 14px;
		background: none;
		color: var(--fg);
	}
	.tile.on {
		background: rgba(90, 150, 255, 0.22);
	}
	.ico {
		position: relative;
		display: grid;
		place-items: center;
	}
	.badge {
		position: absolute;
		top: -6px;
		right: -10px;
		min-width: 17px;
		height: 17px;
		padding: 0 4px;
		border-radius: 999px;
		background: #ff5f57;
		color: #fff;
		font-size: 10px;
		font-weight: 600;
		display: grid;
		place-items: center;
	}
	.run {
		position: absolute;
		bottom: -8px;
		width: 4px;
		height: 4px;
		border-radius: 50%;
		background: rgba(120, 180, 255, 0.95);
	}
	.muted {
		color: var(--muted);
	}
</style>
