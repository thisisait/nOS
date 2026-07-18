<!--
  Taskbar — the open-window strip (bottom-left), separate from the app Dock.

  Shows a live count of open windows and one chip per window for navigation:
  click a chip → focus + un-minimize that window; ✕ → close it. Minimized
  windows read dimmed. This is what stops "every link opens another window and
  I can't get back to them" — the launcher is now singleton (focusApp) AND every
  open window is reachable here.

  Thumbnails: hovering a chip captures that window's DOM to a PNG (html-to-image)
  and shows it in a preview popover — a real live thumbnail, captured on demand
  (no idle cost). Minimized windows aren't in the DOM, so they show a placeholder.
-->
<script lang="ts">
	import { windows, focusWindow, closeWindow } from '$lib/stores/desktop';
	import { toPng } from 'html-to-image';

	// Resolve a small icon for a window's app slug (dock/native icons). Falls back
	// to the first letter. Rendered as escaped text — never {@html}.
	let {
		icon = (app: string) => app.slice(0, 1).toUpperCase()
	}: { icon?: (app: string) => string } = $props();

	// Hover-preview state. `url` is a data: PNG; `x` anchors the popover to the chip.
	let preview = $state<{ id: string; url: string | null; x: number } | null>(null);
	let hoverTimer: ReturnType<typeof setTimeout> | null = null;

	function activate(id: string) {
		focusWindow(id); // focusWindow also clears `min` → restores a minimized window
	}

	function onEnter(id: string, min: boolean, e: MouseEvent) {
		const chip = (e.currentTarget as HTMLElement).getBoundingClientRect();
		const x = chip.left;
		if (hoverTimer) clearTimeout(hoverTimer);
		if (min) {
			preview = { id, url: null, x };
			return;
		}
		// Debounce so a quick sweep across chips doesn't fire a capture per chip.
		hoverTimer = setTimeout(() => void capture(id, x), 220);
	}

	function onLeave() {
		if (hoverTimer) clearTimeout(hoverTimer);
		hoverTimer = null;
		preview = null;
	}

	async function capture(id: string, x: number) {
		const node = document.querySelector<HTMLElement>(`[data-win-id="${CSS.escape(id)}"]`);
		if (!node) {
			preview = { id, url: null, x };
			return;
		}
		try {
			// Small pixelRatio → a light thumbnail; skip fonts to avoid CSP/CORS stalls.
			const url = await toPng(node, { pixelRatio: 0.4, cacheBust: true, skipFonts: true });
			// Only apply if the pointer is still on this chip.
			if (preview === null || preview.id === id) preview = { id, url, x };
		} catch {
			preview = { id, url: null, x };
		}
	}
</script>

{#if $windows.length > 0}
	<nav class="taskbar glass" aria-label="Open windows">
		<span class="count" title="{$windows.length} open window(s)">{$windows.length}</span>
		<div class="chips">
			{#each $windows as win (win.id)}
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div
					class="chip"
					class:min={win.min}
					title={win.title}
					onmouseenter={(e) => onEnter(win.id, win.min, e)}
					onmouseleave={onLeave}
				>
					<button class="open" onclick={() => activate(win.id)}>
						<span class="ico">{icon(win.app).slice(0, 2)}</span>
						<span class="lbl">{win.title}</span>
					</button>
					<button class="x" aria-label={`Close ${win.title}`} onclick={() => closeWindow(win.id)}
						>✕</button
					>
				</div>
			{/each}
		</div>
	</nav>

	{#if preview}
		<div class="preview glass" style="left:{Math.max(8, preview.x)}px" aria-hidden="true">
			{#if preview.url}
				<img src={preview.url} alt="" />
			{:else}
				<div class="ph">Minimized — click to restore</div>
			{/if}
		</div>
	{/if}
{/if}

<style>
	.taskbar {
		position: fixed;
		bottom: 14px;
		left: 14px;
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 8px;
		border-radius: 12px;
		max-width: 46vw;
		z-index: 99999;
	}
	.count {
		flex-shrink: 0;
		min-width: 22px;
		height: 22px;
		display: grid;
		place-items: center;
		border-radius: 999px;
		background: rgba(90, 150, 255, 0.35);
		color: #fff;
		font-size: 12px;
		font-variant-numeric: tabular-nums;
	}
	.chips {
		display: flex;
		gap: 6px;
		overflow-x: auto;
	}
	.chip {
		display: flex;
		align-items: center;
		background: rgba(255, 255, 255, 0.08);
		border-radius: 8px;
		overflow: hidden;
		flex-shrink: 0;
	}
	.chip.min {
		opacity: 0.5;
	}
	.open {
		display: flex;
		align-items: center;
		gap: 6px;
		background: none;
		border: none;
		color: var(--fg);
		padding: 5px 8px;
		cursor: pointer;
		max-width: 160px;
	}
	.open:hover {
		background: rgba(255, 255, 255, 0.06);
	}
	.ico {
		font-size: 13px;
	}
	.lbl {
		font-size: 12px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.x {
		background: none;
		border: none;
		color: var(--muted);
		padding: 5px 7px;
		cursor: pointer;
		font-size: 11px;
	}
	.x:hover {
		color: #ff8080;
		background: rgba(255, 255, 255, 0.06);
	}
	.preview {
		position: fixed;
		bottom: 58px;
		z-index: 99998;
		padding: 5px;
		border-radius: 10px;
		box-shadow: 0 14px 40px rgba(0, 0, 0, 0.5);
		pointer-events: none;
	}
	.preview img {
		display: block;
		width: 260px;
		max-height: 180px;
		object-fit: contain;
		border-radius: 6px;
	}
	.ph {
		width: 200px;
		padding: 18px 10px;
		text-align: center;
		font-size: 12px;
		color: var(--muted);
	}
</style>
