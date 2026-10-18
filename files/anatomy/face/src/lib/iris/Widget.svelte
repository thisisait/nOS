<!--
  One widget on the canvas (a Svelte Flow node, CanvasItem.svelte): a header (move grip, title,
  age, re-run, remove) and its latest answer. The grip is the node's drag handle; arrows on a
  focused grip or node move it, shift+arrows resize (Workspace.svelte, workspace.ts byKey).
-->
<script lang="ts">
	import StatusNote from '$lib/components/ui/StatusNote.svelte';
	import ComponentView from './Component.svelte';
	import { csvName, toCsv } from './csv';
	import Form from './Form.svelte';
	import { lensPrefill } from './form';
	import type { Lens } from './wire';
	import type { WidgetState } from './widgets';
	import { age, type WidgetItem } from './workspace';

	type Submit = { form: string; widget: string; values: Record<string, string | number | boolean> };
	// onexport: the person's click on CSV; the host saves the text and says where (export.rs), or why not.
	let {
		box,
		state: st,
		lens = [],
		now,
		top,
		ontop,
		onrerun,
		onremove,
		onsubmit,
		onexport
	}: {
		box: WidgetItem;
		state: WidgetState | undefined;
		lens?: Lens[];
		now: number;
		top: boolean;
		ontop: () => void;
		onrerun: () => void;
		onremove: () => void;
		onsubmit: (m: Submit) => void;
		onexport?: (name: string, csv: string) => Promise<string>;
	} = $props();

	// `st`: a prop named state would make $state below read as a store.
	let exported: string | null = $state(null);
	const exportRows = async () => {
		if (st?.component?.kind !== 'table_results' || !onexport) return;
		const t = st.component.props;
		exported = await onexport(csvName(t.name || box.title), toCsv(t)).catch(
			(e) => `not saved: ${e}`
		);
	};
</script>

<article class="widget" class:top class:stale={st?.stale} data-widget={box.id}>
	<header>
		<button
			class="handle move"
			aria-label="move {box.title} (arrows move, shift+arrows resize)"
			onpointerdown={ontop}>⠿</button
		>
		<h2>{box.title}</h2>
		<span class="age">{age(st, now)}</span>
		{#if st?.component?.kind === 'table_results'}
			<button
				class="ghost"
				aria-label="export {box.title} as CSV"
				title="the rows shown, as CSV"
				onclick={exportRows}>CSV</button
			>
		{/if}
		<button class="ghost" aria-label="re-run {box.title}" onclick={onrerun}>↻</button>
		<button class="ghost" aria-label="remove {box.title}" onclick={onremove}>×</button>
	</header>
	<div class="body nowheel">
		{#if st?.error}<StatusNote kind="error" block={false}>{st.error}</StatusNote>{/if}
		{#if exported}<p class="added">{exported}</p>{/if}
		{#if st?.component?.kind === 'form'}
			<!-- A new row or a re-run redraws the form from the lens: Add row waits until it is filled again. -->
			{#key st.at}{#key st.added}
					<Form
						form={st.component.props}
						widget={box.id}
						inFlight={!!st.inFlight}
						prefill={lensPrefill(lens, st.component.props.fields)}
						{onsubmit}
					/>
				{/key}{/key}
			{#if st.added}<p class="added">row {st.added} added</p>{/if}
		{:else if st?.component}<ComponentView component={st.component} />{/if}
	</div>
</article>

<style>
	.widget {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		box-sizing: border-box;
		border: 1px solid var(--glass-brd);
		border-radius: 12px;
		background: var(--glass);
		transition: box-shadow 120ms ease;
	}
	.widget.top {
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
