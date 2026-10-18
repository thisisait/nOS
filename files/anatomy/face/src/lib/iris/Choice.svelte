<!--
  A choice Iris asks at a fork (renderers.rs Choice) as native radios, or checkboxes when multi.
  The suggestion starts picked and is marked "navrženo"; every label is a text node. "Odpovědět"
  hands one choice_reply to `onreply` (choice.ts reply); the card shows the answer, held, only once
  `onreply` says it was accepted (choice.ts answer); a refused one stays sendable.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import { answer, initial, reply, toggle } from './choice';
	import type { ChoiceProps, ToThalamus } from './wire';

	let {
		choice,
		session,
		answered = null,
		onreply
	}: {
		choice: ChoiceProps;
		session: string;
		answered?: string[] | null;
		onreply?: (m: Extract<ToThalamus, { t: 'choice_reply' }>) => Promise<boolean>;
	} = $props();

	// A card is drawn once per render message: its props are where it starts, never re-read.
	let picked = $state(untrack(() => initial(choice)));
	let sent: string[] | null = $state(untrack(() => answered));
	let busy = $state(false);
	const send = async () => {
		const m = reply(session, choice, picked, sent !== null || busy);
		if (m?.t !== 'choice_reply') return;
		busy = true;
		sent = await answer(m, onreply);
		busy = false;
	};
</script>

<fieldset class="choice" disabled={sent !== null || busy}>
	<legend>{choice.question}</legend>
	{#each choice.options as o (o.label)}
		<label class="option">
			<input
				type={choice.multi ? 'checkbox' : 'radio'}
				name={choice.id}
				checked={picked.includes(o.label)}
				disabled={sent !== null}
				onchange={() => (picked = toggle(choice, picked, o.label))}
			/>
			<span>{o.label}</span>
			{#if choice.suggested.includes(o.label)}<span class="muted">navrženo</span>{/if}
			{#if o.note}<span class="muted note">{o.note}</span>{/if}
		</label>
	{/each}
	{#if sent !== null}<p class="muted">odpověď: {sent.join(', ')}</p>{/if}
	<button type="button" disabled={sent !== null || busy || !picked.length} onclick={send}
		>Odpovědět</button
	>
</fieldset>

<style>
	.choice {
		display: grid;
		gap: 6px;
		margin: 0;
		padding: 8px;
		border: 1px solid var(--glass-brd);
		border-radius: 12px;
		font-size: 12px;
	}
	legend {
		font-weight: 600;
		font-size: 13px;
	}
	.option {
		display: flex;
		gap: 6px;
		align-items: baseline;
		flex-wrap: wrap;
	}
	.note {
		flex-basis: 100%;
		padding-left: 22px;
	}
	.muted {
		color: var(--muted);
		margin: 0;
	}
	button {
		justify-self: start;
		border: 1px solid var(--glass-brd);
		background: var(--accent);
		color: var(--bg);
		border-radius: 10px;
		padding: 4px 12px;
	}
	button:disabled {
		opacity: 0.4;
	}
</style>
