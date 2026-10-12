<!-- One ToShell message in the chat column. A refusal is shown, never dropped. -->
<script lang="ts">
	import StatusNote from '$ui/StatusNote.svelte';
	import ComponentView from './Component.svelte';
	import type { ToShell } from './wire';

	let { msg }: { msg: ToShell } = $props();
</script>

<div class="msg" data-t={msg.t}>
	{#if msg.t === 'session'}
		<p class="muted">session {msg.session} · {msg.actor} · {msg.model_uri}</p>
	{:else if msg.t === 'text'}
		<p class="text">{msg.text}</p>
	{:else if msg.t === 'render'}
		<ComponentView component={msg.component} />
	{:else if msg.t === 'approval_request'}
		<!-- Only a decided one reaches the log; the waiting one is App's ApprovalCard. -->
		<p class="muted">approval {msg.approval}</p>
		<ComponentView component={msg.component} />
	{:else if msg.t === 'refused'}
		<StatusNote kind="error" title="refused">{msg.reason}</StatusNote>
	{/if}
</div>

<style>
	.msg {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.text {
		margin: 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		line-height: 1.5;
	}
	.muted {
		margin: 0;
		color: var(--muted);
		font-size: 11px;
	}
</style>
