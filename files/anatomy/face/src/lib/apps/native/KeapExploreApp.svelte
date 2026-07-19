<!--
  KeapExploreApp — the KEAP explore graph as a face app.

  KEAP serves `X-Frame-Options: SAMEORIGIN`, so its /explore page REFUSES to
  render in a cross-subdomain iframe here (a cross-origin frame-block is not
  reliably catchable from JS, so we don't try). Default action is therefore
  "open in a new tab" — the graph opens as the signed-in user (Authentik-gated,
  same cookie-domain session). A "try inline" toggle still attempts the iframe
  for the day KEAP relaxes the header to `frame-ancestors`. The URL is a
  non-secret, fetched from /bff/config (the browser never gets a token).
-->
<script lang="ts">
	import { onMount } from 'svelte';

	let url = $state<string | null>(null);
	let ready = $state(false);
	let inline = $state(false);

	onMount(async () => {
		try {
			const r = await fetch('/bff/config', { headers: { accept: 'application/json' } });
			const body = (await r.json()) as { keapExploreUrl?: string };
			url = (body.keapExploreUrl ?? '').trim() || null;
		} catch {
			url = null;
		} finally {
			ready = true;
		}
	});

	function openTab() {
		if (url) window.open(url, '_blank', 'noopener');
	}
</script>

<div class="explore">
	{#if !ready}
		<p class="muted center">loading…</p>
	{:else if !url}
		<div class="card">
			<p>KEAP explore is not configured.</p>
			<p class="muted">
				Set <code>face_keap_explore_url</code> (or enable KEAP) to link the graph.
			</p>
		</div>
	{:else if inline}
		<iframe
			title="KEAP Explore"
			src={url}
			sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
			referrerpolicy="no-referrer-when-downgrade"
		></iframe>
		<button class="link back" onclick={() => (inline = false)}>← back</button>
	{:else}
		<div class="card">
			<h3>KEAP Explore</h3>
			<p class="muted">The knowledge graph opens in KEAP as your signed-in user.</p>
			<button class="cta" onclick={openTab}>Open KEAP Explore ↗</button>
			<p class="note muted">
				Inline embedding is blocked by KEAP's <code>X-Frame-Options</code> — it needs a KEAP-side
				<code>frame-ancestors</code> header.
				<button class="link" onclick={() => (inline = true)}>Try inline anyway</button>
			</p>
		</div>
	{/if}
</div>

<style>
	.explore {
		position: relative;
		height: 100%;
		display: flex;
		flex-direction: column;
		min-height: 0;
	}
	iframe {
		flex: 1;
		width: 100%;
		border: none;
		border-radius: 8px;
		background: #0b0d12;
	}
	.card {
		margin: auto;
		text-align: center;
		max-width: 420px;
		display: flex;
		flex-direction: column;
		gap: 10px;
		padding: 24px;
	}
	.card h3 {
		margin: 0;
	}
	.center {
		margin: auto;
	}
	.cta {
		align-self: center;
		background: var(--accent, #5a96ff);
		color: #fff;
		border: none;
		border-radius: 10px;
		padding: 10px 18px;
		font-size: 14px;
		cursor: pointer;
	}
	.cta:hover {
		filter: brightness(1.08);
	}
	.note {
		font-size: 12px;
	}
	.link {
		background: none;
		border: none;
		color: var(--accent, #5a96ff);
		cursor: pointer;
		padding: 0;
		font: inherit;
	}
	.back {
		position: absolute;
		top: 6px;
		right: 10px;
	}
	.muted {
		color: var(--muted, #9aa4b2);
		font-size: 13px;
	}
	code {
		background: rgba(255, 255, 255, 0.08);
		padding: 1px 5px;
		border-radius: 4px;
	}
</style>
