<!-- One ToShell message in the chat column. A refusal is shown, never dropped. -->
<script lang="ts">
	import StatusNote from '$ui/StatusNote.svelte';
	import Choice from './Choice.svelte';
	import ComponentView from './Component.svelte';
	import DashboardCard from './DashboardCard.svelte';
	import Markdown from './Markdown.svelte';
	import Message from './Message.svelte';
	import { phaseName, type DashboardProps, type ToShell, type ToThalamus } from './wire';

	// onpin: the person clicked "Sem" (the active tab) or "Nový tab" under a render serve gave a pin (genui I6).
	// onchoose: the person answered a choice with "Odpovědět"; drawing one sends nothing.
	// onplace: the person clicked "Place here" or "Place on a new tab" under an offered dashboard; true when it was placed.
	let { msg, onpin, onchoose, onplace }: {
		msg: ToShell;
		onpin?: (m: ToShell, fresh: boolean) => void;
		onchoose?: (m: Extract<ToThalamus, { t: 'choice_reply' }>) => Promise<boolean>;
		onplace?: (d: DashboardProps, here: boolean) => boolean;
	} = $props();
</script>

<div class="msg" data-t={msg.t}>
	{#if msg.t === 'session'}
		<p class="muted">session {msg.session} · {msg.actor} · {msg.model_uri}</p>
	{:else if msg.t === 'text'}
		<!-- Models write markdown in plain text; a string that is not parses to itself. -->
		<Markdown text={msg.text} />
	{:else if msg.t === 'render' && msg.component.kind === 'choice'}
		<Choice choice={msg.component.props} session={msg.session} onreply={onchoose} />
	{:else if msg.t === 'render' && msg.component.kind === 'dashboard'}
		<DashboardCard dashboard={msg.component.props} {onplace} />
	{:else if msg.t === 'render'}
		<ComponentView component={msg.component} />
		{#if msg.pin}
			<div class="pin" role="group" aria-label="Připnout na plochu">
				<svg aria-hidden="true" viewBox="0 0 16 16" width="12" height="12"><path d="M10 1l5 5-2 1-3 3 1 4-1 1-4-4-4 4-1-1 4-4-4-4 1-1 4 1 3-3z" fill="currentColor" /></svg>
				pin
				<button type="button" aria-label="Připnout sem" title="Připnout na tento tab" onclick={() => onpin?.(msg, false)}>Sem</button>
				<button type="button" aria-label="Připnout na nový tab" title="Připnout na nový tab" onclick={() => onpin?.(msg, true)}>Nový tab</button>
			</div>
		{:else if msg.component.kind === 'chart'}
			<p class="muted">jen náhled — Iris neuvedla zdroj čísel</p>
		{/if}
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
	{:else if msg.t === 'form_result'}
		<p class="muted">widget {msg.widget}: row {msg.row} added (form {msg.form})</p>
	{:else if msg.t === 'working_for'}
		<p class="scope">
			{#if msg.scope === 'all'}working for everything (no wall){:else if msg.scope === 'personal'}working on {msg.name} data{:else}working for {msg.name} ({msg.scope.client}){/if}
		</p>
	{:else if msg.t === 'model_options'}
		<!-- App draws these in the header's picker; said here for any other host of a message. -->
		<ul class="muted">
			{#each msg.options as o}<li>{o.backend} {o.model} · {o.processor} · {o.transfers_outside_eu ? 'leaves the EU' : 'EU'}{#if o.current} (current){/if}{#if o.warning} — {o.warning}{/if}</li>{/each}
			{#each msg.refused as r}<li>not offered: {r}</li>{/each}
		</ul>
	{:else if msg.t === 'table_changed'}
		<p class="muted">table {msg.table} changed (row {msg.row})</p>
	{:else if msg.t === 'said'}
		<p class="said">{msg.text}</p>
	{:else if msg.t === 'replay'}
		<!-- App unpacks a replay into its log (resume.ts); drawn here for any other host of a message. -->
		<p class="muted">resumed session {msg.session}: {msg.log.map((m) => m.t).join(', ') || 'nothing said yet'}</p>
		{#each msg.log as m}<Message msg={m} />{/each}
	{:else if msg.t === 'workspace'}
		<p class="muted">{msg.doc ? 'the workspace the thalamus holds' : 'the thalamus holds no workspace yet'}</p>
	{/if}
</div>

<style>
	.msg {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.pin {
		align-self: flex-start;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		border: 1px solid var(--glass-brd);
		background: transparent;
		color: var(--muted);
		border-radius: 6px;
		padding: 1px 6px;
		font-size: 11px;
	}
	.pin button {
		border: 0;
		background: transparent;
		color: inherit;
		font: inherit;
		padding: 0 2px;
		cursor: pointer;
	}
	.pin button:hover {
		color: var(--accent);
	}
	.said {
		align-self: flex-end;
		margin: 0;
		white-space: pre-wrap;
	}
	.scope {
		margin: 0;
		font-weight: 600;
		font-size: 12px;
	}
	.muted {
		margin: 0;
		color: var(--muted);
		font-size: 11px;
	}
</style>
