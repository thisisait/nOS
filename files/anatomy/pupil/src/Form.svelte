<!--
  A widget form (renderers.rs Form) as native inputs; the header and button are the pupil's own words.
  Only the tab's lens prefills (form.ts lensPrefill), and the person may change it; the button waits
  for every required field (form.ts canSubmit). It posts nowhere: a submit goes to `onsubmit` (I5g).
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import { canSubmit, formValues, header, type Draft } from './form';
	import type { FormProps } from './wire';

	type Submit = { form: string; widget: string; values: Record<string, string | number | boolean> };
	let { form, widget = '', inFlight = false, prefill = {}, onsubmit }: {
		form: FormProps; widget?: string; inFlight?: boolean; prefill?: Draft; onsubmit?: (m: Submit) => void;
	} = $props();

	// A form is drawn once per answer: the prefill is where the draft starts, never re-read.
	let draft: Draft = $state(untrack(() => ({ ...prefill })));
	const ready = $derived(canSubmit(form.fields, draft, inFlight));

	const submit = (e: SubmitEvent) => {
		e.preventDefault();
		if (ready) onsubmit?.({ form: form.form, widget, values: formValues(form.fields, draft) });
	};
</script>

<form class="form" onsubmit={submit}>
	<h3>{header(form)}</h3>
	{#each form.fields as f (f.key)}
		<label class="field">
			<span>{f.label}{#if f.required}<span class="muted"> (required)</span>{/if}</span>
			{#if f.kind === 'select'}
				<select bind:value={draft[f.key]} required={f.required}>
					<option value="" disabled selected>choose one</option>
					{#each f.options ?? [] as o}<option value={o}>{o}</option>{/each}
				</select>
			{:else if f.kind === 'bool'}
				<input type="checkbox" bind:checked={draft[f.key]} />
			{:else if f.kind === 'number'}
				<input type="number" bind:value={draft[f.key]} required={f.required} min={f.min} max={f.max} placeholder={f.placeholder} />
			{:else if f.kind === 'date'}
				<input type="date" bind:value={draft[f.key]} required={f.required} />
			{:else}
				<input type="text" bind:value={draft[f.key]} required={f.required} placeholder={f.placeholder} />
			{/if}
		</label>
	{/each}
	{#if form.omitted.length}
		<p class="muted">not editable here: {form.omitted.map((o) => `${o.key} (${o.kind})`).join(', ')}</p>
	{/if}
	<button type="submit" disabled={!ready}>Add row</button>
</form>

<style>
	.form {
		display: grid;
		gap: 8px;
		font-size: 12px;
	}
	h3 {
		margin: 0;
		font-size: 13px;
	}
	.field {
		display: grid;
		gap: 3px;
	}
	.muted {
		color: var(--muted);
		margin: 0;
	}
	button {
		justify-self: start;
	}
</style>
