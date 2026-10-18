<!--
  The floating chat: a fixed panel over the workspace with native `resize: both` and a
  draggable header. The eye, the log, the approval card and the composer are its children.
  Pointer capture is on the header handle only (face-wm-event-gotchas: on the panel it eats clicks).
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Chat } from './workspace';

	let {
		chat,
		top,
		onchat,
		ontop,
		head,
		children
	}: {
		chat: Chat;
		top: boolean;
		onchat: (c: Chat) => void;
		ontop: () => void;
		head: Snippet;
		children: Snippet;
	} = $props();

	let panel: HTMLElement | undefined = $state();
	let drag: { x: number; y: number; cx: number; cy: number } | null = null;

	const down = (e: PointerEvent) => {
		if ((e.target as HTMLElement).closest('button')) return;
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
		drag = { x: chat.x, y: chat.y, cx: e.clientX, cy: e.clientY };
		ontop();
	};
	const moved = (e: PointerEvent) => {
		if (drag)
			onchat({
				...chat,
				x: Math.round(drag.x + e.clientX - drag.cx),
				y: Math.round(drag.y + e.clientY - drag.cy)
			});
	};
	const up = () => (drag = null);
	const STEP = 16;
	const key = (e: KeyboardEvent) => {
		const d = (
			{
				ArrowLeft: [-STEP, 0],
				ArrowRight: [STEP, 0],
				ArrowUp: [0, -STEP],
				ArrowDown: [0, STEP]
			} as Record<string, number[]>
		)[e.key];
		if (!d) return;
		e.preventDefault();
		onchat({ ...chat, x: chat.x + d[0], y: chat.y + d[1] });
	};

	// The native resize handle changes the box; the layout learns its size from here.
	$effect(() => {
		if (!panel || !chat.open) return;
		const ro = new ResizeObserver(() => {
			if (!panel) return;
			const w = Math.round(panel.offsetWidth),
				h = Math.round(panel.offsetHeight);
			if (w !== chat.w || h !== chat.h) onchat({ ...chat, w, h });
		});
		ro.observe(panel);
		return () => ro.disconnect();
	});
</script>

{#if chat.open}
	<section
		class="chat"
		class:top
		bind:this={panel}
		aria-label="Iris chat"
		style="left: {chat.x}px; top: {chat.y}px; width: {chat.w}px; height: {chat.h}px"
		onpointerdowncapture={ontop}
	>
		<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<header
			class="handle"
			role="group"
			tabindex="0"
			aria-label="move the chat (arrow keys)"
			onpointerdown={down}
			onpointermove={moved}
			onpointerup={up}
			onpointercancel={up}
			onkeydown={key}
		>
			{@render head()}
			<button
				class="ghost"
				aria-label="close the chat"
				onclick={() => onchat({ ...chat, open: false })}>×</button
			>
		</header>
		{@render children()}
	</section>
{:else}
	<button class="reopen" onclick={() => onchat({ ...chat, open: true })}>Iris</button>
{/if}

<style>
	.chat {
		position: fixed;
		z-index: 20;
		display: flex;
		flex-direction: column;
		resize: both;
		overflow: hidden;
		min-width: 280px;
		min-height: 240px;
		border: 1px solid var(--glass-brd);
		border-radius: 16px;
		background: var(--bg);
		box-shadow: 0 12px 40px var(--glass);
	}
	.chat.top {
		z-index: 40;
	}
	.handle {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 12px 6px 16px;
		font-weight: 600;
		cursor: grab;
		user-select: none;
		touch-action: none;
	}
	.handle:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}
	.ghost {
		margin-left: auto;
		border: 0;
		background: none;
		color: var(--muted);
		font-size: 16px;
		cursor: pointer;
	}
	.reopen {
		position: fixed;
		right: 16px;
		bottom: 16px;
		z-index: 40;
		border: 1px solid var(--glass-brd);
		background: var(--accent);
		color: var(--bg);
		border-radius: 999px;
		padding: 8px 16px;
		font-weight: 600;
	}
</style>
