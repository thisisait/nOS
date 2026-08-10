<!--
  Badge — a small labelled pill in the shared severity vocabulary.

  Replaces four local reimplementations: the Pulse count chips, the
  "offline defaults" marker in DataTableApp, the paused marker, and the
  "not built" tab marker. All four were the same shape with different colours.

  `count` renders a number ahead of the label so the caller does not have to
  build "3 failing" strings by hand — the commonest use, and the one where a
  zero would otherwise get rendered as a chip saying nothing.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import { toneVars, type Tone } from './tone';

	interface Props {
		tone?: Tone;
		/** Optional leading count. A `0` renders nothing — an empty tally is not
		 *  news, and a row of zeroes is how a summary bar stops being read. */
		count?: number;
		/** Hollow outline instead of a filled pill (for secondary markers). */
		outline?: boolean;
		title?: string;
		children?: Snippet;
	}

	let { tone = 'neutral', count, outline = false, title, children }: Props = $props();

	const vars = $derived(toneVars(tone));
	const showCount = $derived(typeof count === 'number' && count !== 0);
</script>

<span class="badge" class:outline style="--ink: {vars.ink}; --soft: {vars.soft}" {title}>
	{#if showCount}<b>{count}</b>{/if}{#if children}{@render children()}{/if}
</span>

<style>
	.badge {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 11px;
		line-height: 1.6;
		padding: 1px 8px;
		border-radius: 999px;
		background: var(--soft);
		color: var(--ink);
		white-space: nowrap;
	}
	.badge.outline {
		background: none;
		border: 1px solid currentColor;
		opacity: 0.75;
		font-size: 9px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		padding: 0 5px;
	}
	b {
		font-weight: 700;
	}
</style>
