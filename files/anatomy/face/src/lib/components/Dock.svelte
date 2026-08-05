<!--
  Dock — the single macOS-style app strip. Every app lives here (native apps,
  Control Panel, hub services); there is no separate taskbar. A running app shows
  a small count badge; hovering it opens a window switcher with live thumbnails.

  Click behaviour:
    • 0 open windows → launch the app;
    • ≥1 open windows → focus one (a minimised window first, else the back-most,
      so repeated clicks cycle the app's windows forward).

  Thumbnails: html-to-image captures the window DOM on hover (on demand, no idle
  cost) and displays it aspect-preserved (max-w/max-h + auto) so nothing is
  cropped. Minimised windows show a placeholder. Escaped text only, never {@html}.
-->
<script lang="ts">
	import { windows, focusWindow, closeWindow } from '$lib/stores/desktop';
	import { isControlPanelWindow } from '$lib/apps/control-panel/surfaces';
	import { toPng } from 'html-to-image';
	import type { WindowModel } from '$lib/contracts';
	import Icon from './ui/Icon.svelte';

	export interface DockApp {
		/** Matches WindowModel.app (or, for Control Panel, use `isControlPanel`). */
		key: string;
		title: string;
		icon: string;
		isControlPanel?: boolean;
		launch: () => void;
	}

	let { apps = [] as DockApp[] }: { apps?: DockApp[] } = $props();

	function winsFor(app: DockApp): WindowModel[] {
		return $windows.filter((w) =>
			app.isControlPanel ? isControlPanelWindow(w.app) : w.app === app.key
		);
	}

	function onClick(app: DockApp) {
		const wins = winsFor(app);
		if (wins.length === 0) {
			app.launch();
			return;
		}
		const min = wins.find((w) => w.min);
		const target = min ?? [...wins].sort((a, b) => a.z - b.z)[0];
		focusWindow(target.id); // focusWindow also clears `min`
	}

	// ── Hover window-switcher ────────────────────────────────────────────────────
	let panel = $state<{ app: DockApp; cx: number } | null>(null);
	let shots = $state<Record<string, string | null>>({});
	let openTimer: ReturnType<typeof setTimeout> | null = null;
	let closeTimer: ReturnType<typeof setTimeout> | null = null;

	const panelWins = $derived(panel ? winsFor(panel.app) : []);

	function onEnter(app: DockApp, e: MouseEvent) {
		if (closeTimer) clearTimeout(closeTimer);
		if (winsFor(app).length === 0) {
			panel = null;
			return;
		}
		const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
		panel = { app, cx: r.left + r.width / 2 };
		if (openTimer) clearTimeout(openTimer);
		openTimer = setTimeout(() => void captureAll(winsFor(app)), 180);
	}
	function scheduleClose() {
		if (closeTimer) clearTimeout(closeTimer);
		closeTimer = setTimeout(() => (panel = null), 140);
	}
	function cancelClose() {
		if (closeTimer) clearTimeout(closeTimer);
	}

	async function captureAll(wins: WindowModel[]) {
		for (const w of wins) {
			if (w.min) {
				shots = { ...shots, [w.id]: null };
				continue;
			}
			const node = document.querySelector<HTMLElement>(`[data-win-id="${CSS.escape(w.id)}"]`);
			if (!node) {
				shots = { ...shots, [w.id]: null };
				continue;
			}
			try {
				const url = await toPng(node, { pixelRatio: 0.5, cacheBust: true, skipFonts: true });
				shots = { ...shots, [w.id]: url };
			} catch {
				shots = { ...shots, [w.id]: null };
			}
		}
	}

	function pick(id: string) {
		focusWindow(id);
		panel = null;
	}
</script>

<nav class="dock glass" aria-label="Dock">
	{#each apps as app (app.key)}
		{@const n = winsFor(app).length}
		<button
			class="tile"
			title={app.title}
			onclick={() => onClick(app)}
			onmouseenter={(e) => onEnter(app, e)}
			onmouseleave={scheduleClose}
		>
			<span class="ico">
				<!-- Was `app.icon.slice(0, 2)`. slice() counts UTF-16 code units, so a
				     two-emoji icon like "⚡🔥" was cut mid-surrogate and rendered "⚡�".
				     Reachable: hub icons come from an operator-authored hub_card glyph
				     that the BFF passes through untouched. -->
				<Icon icon={app.icon} title={app.title} size={22} labelled={false} />
				{#if n > 0}<span class="badge">{n}</span>{/if}
			</span>
			<span class="lbl">{app.title}</span>
			<span class="run" class:on={n > 0}></span>
		</button>
	{/each}
	{#if apps.length === 0}
		<span class="muted">no apps in catalog</span>
	{/if}
</nav>

{#if panel && panelWins.length > 0}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="switcher glass"
		style="left:{panel.cx}px"
		onmouseenter={cancelClose}
		onmouseleave={scheduleClose}
	>
		{#each panelWins as w (w.id)}
			<div class="sw-item">
				<button class="sw-open" onclick={() => pick(w.id)}>
					<span class="thumb">
						{#if w.min}
							<span class="ph">Minimized</span>
						{:else if shots[w.id]}
							<img src={shots[w.id]} alt="" />
						{:else}
							<span class="ph">…</span>
						{/if}
					</span>
					<span class="sw-title">{w.title}</span>
				</button>
				<button class="sw-x" aria-label={`Close ${w.title}`} onclick={() => closeWindow(w.id)}
					>✕</button
				>
			</div>
		{/each}
	</div>
{/if}

<style>
	.dock {
		position: fixed;
		bottom: 14px;
		left: 50%;
		transform: translateX(-50%);
		display: flex;
		gap: 10px;
		padding: 10px 14px;
		align-items: flex-end;
		max-width: 92vw;
		overflow-x: auto;
		z-index: 100000;
		border-radius: 18px;
	}
	.tile {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 3px;
		background: none;
		border: none;
		width: 64px;
		cursor: pointer;
	}
	.ico {
		position: relative;
		width: 46px;
		height: 46px;
		display: grid;
		place-items: center;
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.08);
		font-size: 13px;
		text-transform: uppercase;
		transition: transform 120ms ease-out;
	}
	.tile:hover .ico {
		transform: translateY(-4px) scale(1.06);
	}
	.badge {
		position: absolute;
		top: -5px;
		right: -5px;
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
		box-shadow: 0 0 0 2px rgba(12, 14, 22, 0.9);
	}
	.lbl {
		font-size: 11px;
		color: var(--muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 64px;
	}
	.run {
		width: 4px;
		height: 4px;
		border-radius: 50%;
		background: transparent;
	}
	.run.on {
		background: rgba(120, 180, 255, 0.95);
	}
	.muted {
		color: var(--muted);
	}
	.switcher {
		position: fixed;
		bottom: 92px;
		transform: translateX(-50%);
		z-index: 100001;
		display: flex;
		gap: 8px;
		padding: 8px;
		border-radius: 14px;
		max-width: 80vw;
		overflow-x: auto;
		box-shadow: 0 18px 50px rgba(0, 0, 0, 0.55);
	}
	.sw-item {
		position: relative;
		flex-shrink: 0;
	}
	.sw-open {
		display: flex;
		flex-direction: column;
		gap: 5px;
		background: rgba(255, 255, 255, 0.05);
		border: 1px solid var(--glass-brd);
		border-radius: 10px;
		padding: 6px;
		cursor: pointer;
		color: var(--fg);
	}
	.sw-open:hover {
		background: rgba(90, 150, 255, 0.18);
	}
	.thumb {
		display: grid;
		place-items: center;
		width: 200px;
		height: 124px;
		background: rgba(0, 0, 0, 0.25);
		border-radius: 6px;
		overflow: hidden;
	}
	.thumb img {
		display: block;
		max-width: 100%;
		max-height: 100%;
		width: auto;
		height: auto;
		border-radius: 4px;
	}
	.ph {
		font-size: 12px;
		color: var(--muted);
	}
	.sw-title {
		font-size: 12px;
		max-width: 200px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.sw-x {
		position: absolute;
		top: 2px;
		right: 2px;
		width: 20px;
		height: 20px;
		border: none;
		border-radius: 6px;
		background: rgba(0, 0, 0, 0.5);
		color: #fff;
		font-size: 11px;
		cursor: pointer;
	}
	.sw-x:hover {
		color: #ff8080;
	}
</style>
