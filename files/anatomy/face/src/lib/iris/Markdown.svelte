<!-- Model text as markdown (markdown.ts), every node a text node: no anchor, no raw HTML. -->
<script lang="ts">
	import { parse, type Inline } from './markdown';

	let { text }: { text: string } = $props();
	const blocks = $derived(parse(text));
</script>

{#snippet line(xs: Inline[])}{#each xs as x}{#if x.t === 'strong'}<strong>{x.text}</strong>{:else if x.t === 'em'}<em>{x.text}</em>{:else if x.t === 'code'}<code>{x.text}</code>{:else if x.t === 'link'}{x.url ? `${x.text} (${x.url})` : x.text}{:else}{x.text}{/if}{/each}{/snippet}

<div class="md">
	{#each blocks as b}
		{#if b.t === 'h'}
			<svelte:element this={`h${b.level}`}>{@render line(b.inl)}</svelte:element>
		{:else if b.t === 'p'}
			<p>{@render line(b.inl)}</p>
		{:else if b.t === 'hr'}
			<hr />
		{:else if b.t === 'ul'}
			<ul>{#each b.items as it}<li>{@render line(it.inl)}{#if it.sub.length}<ul>{#each it.sub as s}<li>{@render line(s)}</li>{/each}</ul>{/if}</li>{/each}</ul>
		{:else if b.t === 'ol'}
			<ol>{#each b.items as it}<li value={it.n}>{@render line(it.inl)}</li>{/each}</ol>
		{:else}
			<pre><code>{b.text}</code></pre>
		{/if}
	{/each}
</div>

<style>
	.md {
		display: flex;
		flex-direction: column;
		gap: 6px;
		line-height: 1.5;
		overflow-wrap: anywhere;
	}
	h1,
	h2,
	h3,
	p,
	ul,
	ol,
	pre {
		margin: 0;
	}
	h1 {
		font-size: 15px;
	}
	h2 {
		font-size: 14px;
	}
	h3 {
		font-size: 13px;
	}
	p {
		white-space: pre-wrap;
	}
	ul,
	ol {
		padding-left: 18px;
	}
	code {
		font-family: ui-monospace, monospace;
		font-size: 0.92em;
	}
	pre {
		padding: 6px 8px;
		border: 1px solid var(--glass-brd);
		border-radius: 6px;
		overflow-x: auto;
	}
</style>
