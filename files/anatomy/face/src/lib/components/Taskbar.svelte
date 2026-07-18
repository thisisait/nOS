<!--
  Taskbar — the open-window strip (bottom-left), separate from the app Dock.

  Shows a live count of open windows and one chip per window for navigation:
  click a chip → focus + un-minimize that window; ✕ → close it. Minimized
  windows read dimmed. This is what stops "every link opens another window and
  I can't get back to them" — the launcher is now singleton (focusApp) AND every
  open window is reachable here.

  Thumbnails: chips currently carry the app icon + title. True live previews
  (canvas snapshots) are a follow-up (docs/plans/nos-face-shell-v2.md).
-->
<script lang="ts">
	import { windows, focusWindow, closeWindow } from '$lib/stores/desktop';

	// Resolve a small icon for a window's app slug (dock/native icons). Falls back
	// to the first letter. Rendered as escaped text — never {@html}.
	let {
		icon = (app: string) => app.slice(0, 1).toUpperCase()
	}: { icon?: (app: string) => string } = $props();

	function activate(id: string) {
		focusWindow(id); // focusWindow also clears `min` → restores a minimized window
	}
</script>

{#if $windows.length > 0}
	<nav class="taskbar glass" aria-label="Open windows">
		<span class="count" title="{$windows.length} open window(s)">{$windows.length}</span>
		<div class="chips">
			{#each $windows as win (win.id)}
				<div class="chip" class:min={win.min} title={win.title}>
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
</style>
