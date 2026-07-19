<!--
  ServiceFrame — the single iframe primitive for a service window.

  Many self-hosted services set `X-Frame-Options: SAMEORIGIN` (or a
  `frame-ancestors 'self'` CSP), so they REFUSE to render in a cross-subdomain
  iframe here — and a cross-origin frame-block is NOT reliably catchable from
  JS, so we never pretend to auto-detect it. Honest UX instead:
    • embed === false  → operator declared it non-embeddable: an open-↗ card
      (with a "try inline anyway" escape for the day the service relaxes it).
    • otherwise         → render the iframe, but keep "Open ↗" in the top bar
      as the always-available fallback if the frame comes up blank.
  The URL is a non-secret (Authentik-gated, same cookie-domain session) and
  renders as an escaped attribute — never {@html}.
-->
<script lang="ts">
	let { url, title, embed }: { url: string; title: string; embed?: boolean } = $props();

	const valid = $derived(/^https?:\/\//.test(url));
	// Operator said non-embeddable (embed===false) → start on the card; else go
	// straight to inline. `override` = the user's explicit "try inline anyway"
	// choice, which wins once set (null = follow the embed declaration).
	let override = $state<boolean | null>(null);
	const inline = $derived(override ?? embed !== false);
	let nonce = $state(0);

	function openTab() {
		if (valid) window.open(url, '_blank', 'noopener');
	}
	function reload() {
		nonce += 1;
	}
</script>

<div class="frame">
	{#if !valid}
		<p class="muted center">This service has no valid URL to open.</p>
	{:else}
		<div class="bar">
			<span class="ttl">{title}</span>
			<span class="spacer"></span>
			{#if inline}
				<button class="link" onclick={reload} title="Reload">⟳</button>
			{/if}
			<button class="link" onclick={openTab} title="Open in a new tab">Open ↗</button>
		</div>

		{#if inline}
			{#key nonce}
				<iframe
					{title}
					src={url}
					sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
					referrerpolicy="no-referrer-when-downgrade"
				></iframe>
			{/key}
		{:else}
			<div class="card">
				<h3>{title}</h3>
				<p class="muted">Opens as your signed-in user (Authentik-gated).</p>
				<button class="cta" onclick={openTab}>Open {title} ↗</button>
				<p class="note muted">
					Inline embedding is blocked by this service's <code>X-Frame-Options</code>.
					<button class="link inlinebtn" onclick={() => (override = true)}>Try inline anyway</button
					>
				</p>
			</div>
		{/if}
	{/if}
</div>

<style>
	.frame {
		position: relative;
		height: 100%;
		display: flex;
		flex-direction: column;
		min-height: 0;
	}
	.bar {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 2px 2px 8px;
		font-size: 12px;
	}
	.ttl {
		color: var(--muted, #9aa4b2);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.spacer {
		flex: 1;
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
	.inlinebtn {
		margin-left: 4px;
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
