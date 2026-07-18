<script lang="ts">
	import { onMount } from 'svelte';
	import { windows, openWindow } from '$lib/stores/desktop';
	import Window from '$lib/components/Window.svelte';
	import { hubApps } from '$lib/api/hub';
	import type { HubApp } from '$lib/contracts';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	let apps = $state<HubApp[]>([]);

	onMount(async () => {
		try {
			apps = await hubApps();
		} catch {
			apps = [];
		}
	});

	function launch(app: HubApp) {
		openWindow({ app: app.slug, title: app.title, w: 720, h: 480 });
	}
</script>

<div class="desktop">
	<header class="menubar glass">
		<strong>nOS</strong>
		<span class="spacer"></span>
		{#if data.identity.authenticated}
			<span class="user">{data.identity.username}</span>
		{:else}
			<span class="user muted">not signed in</span>
		{/if}
	</header>

	{#each $windows as win (win.id)}
		<Window {win}>
			<div class="placeholder">
				<p>{win.title}</p>
				<p class="muted">nos-native app surface — Wave 1 (G5) mounts real API-calling apps here.</p>
			</div>
		</Window>
	{/each}

	<nav class="dock glass" aria-label="Dock">
		{#if apps.length === 0}
			<span class="muted">no apps in catalog</span>
		{/if}
		{#each apps as app (app.slug)}
			<button class="tile" title={app.description} onclick={() => launch(app)}>
				<span class="ico">{app.icon.slice(0, 2)}</span>
				<span class="lbl">{app.title}</span>
			</button>
		{/each}
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
