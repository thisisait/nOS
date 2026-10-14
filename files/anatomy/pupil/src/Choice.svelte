<!--
  A choice Iris asks at a fork (renderers.rs Choice) as native radios, or checkboxes when multi.
  The suggestion starts picked and is marked "navrženo"; every label is a text node. "Odpovědět"
  hands one choice_reply to `onreply` (choice.ts reply); then the card shows the answer, held.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import { initial, reply, toggle } from './choice';
	import type { ChoiceProps, ToThalamus } from './wire';

	let { choice, session, answered = null, onreply }: {
		choice: ChoiceProps;
		session: string;
		answered?: string[] | null;
		onreply?: (m: Extract<ToThalamus, { t: 'choice_reply' }>) => void;
	} = $props();

	// A card is drawn once per render message: its props are where it starts, never re-read.
	let picked = $state(untrack(() => initial(choice)));
	let sent: string[] | null = $state(untrack(() => answered));
	const send = () => {
		const m = reply(session, choice, picked, sent !== null);
		if (m?.t !== 'choice_reply') return;
		sent = m.picked;
		onreply?.(m);
	};
</script>

<fieldset class="choice" disabled={sent !== null}>
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
	<button type="button" disabled={sent !== null || !picked.length} onclick={send}>Odpovědět</button>
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
