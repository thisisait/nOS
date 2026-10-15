<!--
  One widget on the grid: a header (move handle, title, age, re-run, remove), its latest answer,
  and a resize handle in the corner. Pointer capture is on a handle only (face-wm-event-gotchas);
  arrows on a focused handle move it, shift+arrows resize, through workspace.ts place().
-->
<script lang="ts">
	import StatusNote from '$ui/StatusNote.svelte';
	import ComponentView from './Component.svelte';
	import Form from './Form.svelte';
	import { lensPrefill } from './form';
	import type { Lens } from './wire';
	import type { WidgetState } from './widgets';
	import { age, byKey, byPointer, type Grid, type WidgetBox } from './workspace';

	type Submit = { form: string; widget: string; values: Record<string, string | number | boolean> };
	let { box, state, lens = [], now, top, unit, onplace, ontop, onrerun, onremove, onsubmit }: {
		box: WidgetBox; state: WidgetState | undefined; lens?: Lens[]; now: number; top: boolean; unit: () => { col: number; row: number };
		onplace: (g: Grid) => void; ontop: () => void; onrerun: () => void; onremove: () => void; onsubmit: (m: Submit) => void;
	} = $props();

	let drag: { mode: 'move' | 'resize'; start: Grid; cx: number; cy: number; u: { col: number; row: number } } | null = null;

	const grab = (mode: 'move' | 'resize') => (e: PointerEvent) => {
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
		drag = { mode, start: { x: box.x, y: box.y, w: box.w, h: box.h }, cx: e.clientX, cy: e.clientY, u: unit() };
		ontop();
	};
	const moved = (e: PointerEvent) => {
		if (drag) onplace(byPointer(drag.start, drag.mode, e.clientX - drag.cx, e.clientY - drag.cy, drag.u.col, drag.u.row));
	};
	const up = () => (drag = null);
	const key = (resizeOnly: boolean) => (e: KeyboardEvent) => {
		const g = byKey(box, e.key, resizeOnly || e.shiftKey);
		if (!g) return;
		e.preventDefault();
		onplace(g);
	};
</script>

<article
	class="widget"
	class:top
	class:stale={state?.stale}
	data-widget={box.id}
	style="grid-column: {box.x + 1} / span {box.w}; grid-row: {box.y + 1} / span {box.h}"
>
	<header>
		<button
			class="handle move"
			aria-label="move {box.title} (arrows move, shift+arrows resize)"
			onpointerdown={grab('move')}
			onpointermove={moved}
			onpointerup={up}
			onpointercancel={up}
			onkeydown={key(false)}>⠿</button
		>
		<h2>{box.title}</h2>
		<span class="age">{age(state, now)}</span>
		<button class="ghost" aria-label="re-run {box.title}" onclick={onrerun}>↻</button>
		<button class="ghost" aria-label="remove {box.title}" onclick={onremove}>×</button>
	</header>
	<div class="body">
		{#if state?.error}<StatusNote kind="error" block={false}>{state.error}</StatusNote>{/if}
		{#if state?.component?.kind === 'form'}
			<!-- A new row or a re-run redraws the form from the lens: Add row waits until it is filled again. -->
			{#key state.at}{#key state.added}
				<Form form={state.component.props} widget={box.id} inFlight={!!state.inFlight} prefill={lensPrefill(lens, state.component.props.fields)} {onsubmit} />
			{/key}{/key}
			{#if state.added}<p class="added">row {state.added} added</p>{/if}
		{:else if state?.component}<ComponentView component={state.component} />{/if}
	</div>
	<button
		class="handle resize"
		aria-label="resize {box.title} (arrows)"
		onpointerdown={grab('resize')}
		onpointermove={moved}
		onpointerup={up}
		onpointercancel={up}
		onkeydown={key(true)}
	></button>
</article>

<style>
	.widget {
		position: relative;
		z-index: 1;
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
		border: 1px solid var(--glass-brd);
		border-radius: 12px;
		background: var(--glass);
		transition: box-shadow 120ms ease;
	}
	.widget.top {
		z-index: 30;
		box-shadow: 0 8px 28px var(--glass);
	}
	.widget.stale .age {
		color: var(--warn);
	}
	header {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 8px;
		border-bottom: 1px solid var(--glass-brd);
	}
	h2 {
		flex: 1;
		margin: 0;
		font-size: 13px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.age {
		color: var(--muted);
		font-size: 11px;
		white-space: nowrap;
	}
	.body {
		flex: 1;
		overflow: auto;
		padding: 8px;
	}
	.handle {
		border: 0;
		background: none;
		color: var(--muted);
		touch-action: none;
	}
	.move {
		cursor: grab;
	}
	.resize {
		position: absolute;
		right: 2px;
		bottom: 2px;
		width: 14px;
		height: 14px;
		cursor: nwse-resize;
		border-right: 2px solid var(--muted);
		border-bottom: 2px solid var(--muted);
		border-radius: 0 0 8px 0;
	}
	.handle:focus-visible {
		outline: 2px solid var(--accent);
	}
	.ghost {
		border: 0;
		background: none;
		color: var(--muted);
		cursor: pointer;
	}
	.added {
		margin: 4px 0 0;
		color: var(--muted);
		font-size: 11px;
	}
	@media (prefers-reduced-motion: reduce) {
		.widget {
			transition: none;
		}
	}
</style>
