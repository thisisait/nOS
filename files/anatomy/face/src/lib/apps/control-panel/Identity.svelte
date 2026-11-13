<script lang="ts">
	/**
	 * Identity surface: the estate's root CA digest on a second channel (row
	 * nos-root-ca-fingerprint-second-channel). A device that fetched /nos-root-ca.crt over plain
	 * http compares the sha256 shown here. Every value is rendered as text.
	 */
	import { onMount } from 'svelte';
	import { bffGet } from '$lib/api/client';
	import type { RootCaView } from '$lib/security/rootCa';

	let view = $state<RootCaView | null>(null);
	let failed = $state('');

	onMount(async () => {
		try {
			view = await bffGet<RootCaView>('/bff/estate/root-ca');
		} catch (e) {
			failed = e instanceof Error ? e.message.slice(0, 120) : 'no answer';
		}
	});
</script>

<section class="id">
	<h3>Root certificate</h3>
	{#if failed}
		<p class="warn">UNKNOWN: the face could not ask ({failed}).</p>
	{:else if !view}
		<p class="muted">Asking Bone…</p>
	{:else if 'unknown' in view.trusted}
		<p class="warn">UNKNOWN: {view.trusted.unknown}</p>
	{:else}
		<p>This host signs with the root CA</p>
		<code class="sha">{view.trusted.sha256}</code>
		{#if view.trusted.subject}<p class="muted">{view.trusted.subject}</p>{/if}
		{#if view.trusted.notAfter}<p class="muted">valid until {view.trusted.notAfter}</p>{/if}
		{#if view.agree}
			<p class="ok">The edge serves the same certificate.</p>
		{:else if 'sha256' in view.served}
			<p class="bad">The edge serves a DIFFERENT certificate (sha256 {view.served.sha256}).</p>
		{:else}
			<p class="warn">What the edge serves is UNKNOWN ({view.served.unknown}).</p>
		{/if}
		<p>Compare on the device that downloaded it:</p>
		<code>openssl x509 -noout -fingerprint -sha256 -in nos-root-ca.crt</code>
		<p class="muted">macOS, Linux, Windows (Git Bash). On the host: <code>nos ca</code></p>
	{/if}
	<p class="muted">
		This proves the download matches what this host signs with. It cannot prove the host itself is
		honest.
	</p>
</section>

<style>
	.id {
		display: grid;
		gap: 8px;
		font-size: 13px;
	}
	.sha {
		word-break: break-all;
		font-size: 12px;
	}
	.muted {
		color: var(--muted);
	}
	.ok {
		color: var(--ok);
	}
	.bad {
		color: var(--bad);
		font-weight: 600;
	}
	.warn {
		color: var(--warn);
	}
</style>
