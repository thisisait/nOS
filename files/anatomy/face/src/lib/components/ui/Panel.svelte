<!--
  Panel — in-window furniture. The box an app puts content in.

  WHY: `.card` existed three times with two different meanings. KeapExploreApp
  and ServiceFrame carried BYTE-IDENTICAL rules (margin:auto, text-align:center,
  max-width:420px, flex column, gap:10px, padding:24px) — a literal copy-paste —
  while BoneView's `.card` was a translucent content box with different padding
  and radius. One word, two things, and neither could be changed without
  guessing which screens it would move.

  So the two meanings are named:

    variant="content"  a surface holding data. Fills its slot.
    variant="message"  a centred, bounded block that says something to the
                       operator when there is nothing else to show.

  A `title` renders as a section heading with the shell's uppercase label
  treatment, which four components had each re-declared.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		variant?: 'content' | 'message';
		title?: string;
		/** Right-hand slot in the heading row — counts, badges, actions. */
		aside?: Snippet;
		children?: Snippet;
	}

	let { variant = 'content', title = '', aside, children }: Props = $props();
</script>

<section class="panel" class:message={variant === 'message'}>
	{#if title || aside}
		<header>
			{#if title}<h3>{title}</h3>{/if}
			{#if aside}<div class="aside">{@render aside()}</div>{/if}
		</header>
	{/if}
	{#if children}{@render children()}{/if}
</section>

<style>
	.panel {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 12px;
		border-radius: 10px;
		background: rgba(255, 255, 255, 0.03);
		min-width: 0;
	}
	.panel.message {
		margin: auto;
		max-width: 420px;
		padding: 24px;
		gap: 10px;
		text-align: center;
		background: none;
	}
	header {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.panel.message header {
		justify-content: center;
	}
	h3 {
		margin: 0;
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--muted, #9aa4b2);
		font-weight: 600;
	}
	.panel.message h3 {
		font-size: 14px;
		text-transform: none;
		letter-spacing: 0;
		color: var(--fg, #e8ecf3);
	}
	.aside {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.panel.message .aside {
		margin-left: 0;
	}
</style>
