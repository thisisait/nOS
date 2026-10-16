<!-- Iris's model for this session (W5): a native select over serve's options; the pick takes effect on the next turn. -->
<script lang="ts">
	import { keyOf, labelOf, pickOf } from './model';
	import type { ModelOption, ToThalamus } from './wire';

	// refused: what serve left out and why, said in the select's title rather than dropped.
	let { options, refused = [], onpick }: { options: ModelOption[]; refused?: string[]; onpick: (m: ToThalamus) => void } = $props();
	const current = $derived(options.find((o) => o.current));
</script>

<select
	aria-label="Iris model for this session"
	title={['takes effect on the next turn', ...refused.map((r) => `not offered: ${r}`)].join('\n')}
	value={current ? keyOf(current) : ''}
	onchange={(e) => {
		const m = pickOf(options, e.currentTarget.value);
		if (m) onpick(m);
	}}
>
	{#if !current}<option value="" disabled>no model</option>{/if}
	{#each options as o (keyOf(o))}
		<option value={keyOf(o)}>{labelOf(o)}</option>
	{/each}
</select>
{#if current?.warning}<span class="warn" title={current.warning}>small</span>{/if}

<style>
	select {
		max-width: 260px;
		font-size: 11px;
		background: transparent;
		color: inherit;
		border: 1px solid var(--glass-brd);
		border-radius: 6px;
	}
	.warn {
		font-size: 11px;
		color: var(--warn-ink);
		border: 1px solid currentColor;
		border-radius: 6px;
		padding: 0 6px;
	}
</style>
