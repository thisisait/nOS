<!-- One ToShell message in the chat column. A refusal is shown, never dropped. -->
<script lang="ts">
	import StatusNote from '$ui/StatusNote.svelte';
	import ComponentView from './Component.svelte';
	import Markdown from './Markdown.svelte';
	import { phaseName, type ToShell } from './wire';

	let { msg }: { msg: ToShell } = $props();
</script>

<div class="msg" data-t={msg.t}>
	{#if msg.t === 'session'}
		<p class="muted">session {msg.session} · {msg.actor} · {msg.model_uri}</p>
	{:else if msg.t === 'text'}
		<!-- Models write markdown in plain text; a string that is not parses to itself. -->
		<Markdown text={msg.text} />
	{:else if msg.t === 'render'}
		<ComponentView component={msg.component} />
	{:else if msg.t === 'approval_request'}
		<!-- Only a decided one reaches the log; the waiting one is App's ApprovalCard. -->
		<p class="muted">approval {msg.approval}</p>
		<ComponentView component={msg.component} />
	{:else if msg.t === 'refused'}
		<StatusNote kind="error" title="refused">{#if msg.widget}widget {msg.widget}: {/if}{msg.reason}</StatusNote>
	{:else if msg.t === 'activity'}
		<!-- App logs only a tool run; every phase goes to the eye. -->
		<p class="muted">→ {phaseName(msg.phase)}</p>
	{:else if msg.t === 'widget'}
		<!-- App routes these to their widget (widgets.ts); drawn here for any other host of a message. -->
		<p class="muted">widget {msg.widget}</p>
		<ComponentView component={msg.component} />
	{/if}
</div>

<style>
	.msg {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.muted {
		margin: 0;
		color: var(--muted);
		font-size: 11px;
	}
</style>
