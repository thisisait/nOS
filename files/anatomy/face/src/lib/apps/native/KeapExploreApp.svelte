<!--
  KeapExploreApp — the KEAP explore graph as a face app.

  KEAP supports embedding (Authentik-gated, same cookie-domain session), so this
  is the sanctioned iframe path: the window body is the live KEAP /explore graph,
  loaded as the signed-in user. The URL is a non-secret, fetched from /bff/config
  (the browser never gets a token). If unconfigured, we say so rather than iframe
  an empty src.
-->
<script lang="ts">
	import { onMount } from 'svelte';

	let url = $state<string | null>(null);
	let ready = $state(false);

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
</script>

<div class="explore">
	{#if !ready}
		<p class="muted">loading…</p>
	{:else if url}
		<iframe
			title="KEAP Explore"
			src={url}
			sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
			referrerpolicy="no-referrer-when-downgrade"
		></iframe>
	{:else}
		<div class="empty">
			<p>KEAP explore is not configured.</p>
			<p class="muted">
				Set <code>face_keap_explore_url</code> (or enable KEAP) to embed the graph.
			</p>
		</div>
	{/if}
</div>

<style>
	.explore {
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
	.empty {
		margin: auto;
		text-align: center;
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
