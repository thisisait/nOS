<!--
  StatusNote — the one way this shell says "there is nothing to show, and here
  is which kind of nothing".

  Four kinds, and they render differently on purpose. The temptation this
  component exists to remove is the one-liner `<p class="muted">loading…</p>`
  that then gets copied and, three screens later, is used for an empty list and
  for an unreachable API alike. When those look the same, an operator reads a
  failed fetch as "nothing is wrong" — the exact misreading that let a
  container serve its own installer for ten days behind a green dashboard.

  Usage:
    <StatusNote kind="unwired">NOS_WING_API_TOKEN is not set.</StatusNote>
    <StatusNote kind="empty" title="No runs recorded" />

  Text is rendered escaped via {@render}; there is no {@html} path.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import { STATUS_TONE, STATUS_GLYPH, toneVars, type StatusKind } from './tone';

	interface Props {
		kind: StatusKind;
		/** Short headline. Optional — a bare body reads fine for `loading`. */
		title?: string;
		/** Set false for a compact inline note inside a list or a row. */
		block?: boolean;
		children?: Snippet;
	}

	let { kind, title = '', block = true, children }: Props = $props();

	const vars = $derived(toneVars(STATUS_TONE[kind]));
</script>

<p
	class="note"
	class:block
	data-kind={kind}
	style="--ink: {vars.ink}; --soft: {vars.soft}"
	role={kind === 'error' ? 'alert' : undefined}
>
	<span class="glyph" aria-hidden="true">{STATUS_GLYPH[kind]}</span>
	{#if title}<span class="title">{title}</span>{/if}
	{#if children}<span class="body">{@render children()}</span>{/if}
</p>

<style>
	.note {
		display: flex;
		align-items: baseline;
		gap: 8px;
		margin: 0;
		font-size: 12px;
		line-height: 1.6;
		color: var(--ink);
	}
	.note.block {
		padding: 10px 12px;
		background: var(--soft);
		border-radius: 8px;
	}
	.glyph {
		font-family: ui-monospace, monospace;
		opacity: 0.85;
		flex-shrink: 0;
	}
	.title {
		font-weight: 600;
	}
	.body {
		opacity: 0.92;
	}
	/* `loading` is the only transient kind; a pulse marks it as "still asking"
	   rather than "this is the answer". */
	.note[data-kind='loading'] .glyph {
		animation: blink 1.4s ease-in-out infinite;
	}
	@keyframes blink {
		0%,
		100% {
			opacity: 0.3;
		}
		50% {
			opacity: 1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.note[data-kind='loading'] .glyph {
			animation: none;
		}
	}
</style>
