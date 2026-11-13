<!--
  The selected roadmap row's detail panel, shared by the Roadmap graph and the
  Skill tree. Read-only inspection: a selection never writes. `children` adds
  view-specific lines above the fields (the skill tree's state and blocker).
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { DataTableRow } from '$lib/contracts';

	let { row, onclose, children }: { row: DataTableRow; onclose: () => void; children?: Snippet } =
		$props();

	// The row fields worth showing, in a sensible reading order; only the ones
	// with a value render (a roadmap row fills a handful, not all 20 columns).
	const FIELDS: { key: string; label: string }[] = [
		{ key: 'status', label: 'Status' },
		{ key: 'kind', label: 'Kind' },
		{ key: 'track', label: 'Track' },
		{ key: 'severity', label: 'Severity' },
		{ key: 'effort', label: 'Effort' },
		{ key: 'owner', label: 'Owner' },
		{ key: 'parent', label: 'Parent' },
		{ key: 'target', label: 'Target' },
		{ key: 'occurred_at', label: 'Landed' },
		{ key: 'verified', label: 'Verified' },
		{ key: 'verified_by', label: 'Verified by' },
		{ key: 'source', label: 'Source' },
		{ key: 'release', label: 'Release' }
	];
	function cellOf(key: string): string {
		const v = row[key];
		return v == null ? '' : String(v);
	}
</script>

<aside class="detail" aria-label="Row detail">
	<div class="detail-head">
		<strong>{cellOf('title') || cellOf('slug')}</strong>
		<button class="close" onclick={onclose} aria-label="Close detail">×</button>
	</div>
	<code class="slug">{cellOf('slug')}</code>
	{@render children?.()}
	<dl>
		{#each FIELDS as f}
			{#if cellOf(f.key)}
				<dt>{f.label}</dt>
				<dd>{cellOf(f.key)}</dd>
			{/if}
		{/each}
	</dl>
	{#if cellOf('body')}
		<p class="body">{cellOf('body')}</p>
	{/if}
</aside>

<style>
	.detail {
		position: absolute;
		top: 0.6rem;
		right: 0.6rem;
		width: 260px;
		max-height: calc(100% - 1.2rem);
		overflow-y: auto;
		background: var(--panel, #1b1f27);
		border: 1px solid var(--border, #333a45);
		border-radius: 8px;
		padding: 0.6rem 0.75rem;
		font-size: 0.82rem;
		z-index: 5;
	}
	.detail-head {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
	}
	.detail-head strong {
		flex: 1 1 auto;
	}
	.close {
		background: transparent;
		border: none;
		color: var(--muted, #9aa4b2);
		font-size: 1.1rem;
		line-height: 1;
		cursor: pointer;
	}
	.slug {
		color: var(--muted, #9aa4b2);
		font-size: 0.75rem;
	}
	.detail dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.15rem 0.6rem;
		margin: 0.5rem 0 0;
	}
	.detail dt {
		color: var(--muted, #9aa4b2);
	}
	.detail dd {
		margin: 0;
		word-break: break-word;
	}
	.detail .body {
		margin: 0.6rem 0 0;
		padding-top: 0.5rem;
		border-top: 1px solid var(--border, #2a2f38);
		color: var(--fg, #e8ecf3);
		white-space: pre-wrap;
	}
</style>
