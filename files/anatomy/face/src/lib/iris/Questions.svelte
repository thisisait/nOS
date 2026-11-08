<script lang="ts">
	// The agents' open questions; null is UNKNOWN (not read yet, or refused), never "none".
	import StatusNote from '$lib/components/ui/StatusNote.svelte';
	import type { Question } from './questions';

	let {
		items,
		results,
		onanswer,
		onrefresh
	}: {
		items: Question[] | null;
		results: Record<string, string>;
		onanswer: (uuid: string, text: string) => void;
		onrefresh: () => void;
	} = $props();
	let draft: Record<string, string> = $state({});
</script>

<section class="questions" aria-label="agents' questions">
	<header>
		<strong>Agents' questions</strong>
		<button class="ghost" onclick={onrefresh}>refresh</button>
	</header>
	{#if items === null}
		<StatusNote kind="unwired" block={false}>not read yet</StatusNote>
	{:else if items.length === 0}
		<p class="none">No agent is waiting for an answer.</p>
	{:else}
		<ul>
			{#each items as q (q.uuid)}
				<li>
					<p class="who">
						{q.agent} asks{#if q.expires}<span> · until {q.expires}</span>{/if}
					</p>
					<p class="prompt">{q.prompt}</p>
					{#if results[q.uuid]}
						<p class="result">{results[q.uuid]}</p>
					{:else}
						<form
							onsubmit={(e) => {
								e.preventDefault();
								onanswer(q.uuid, draft[q.uuid] ?? '');
							}}
						>
							<label for={`answer-${q.uuid}`}>Answer</label>
							<input id={`answer-${q.uuid}`} bind:value={draft[q.uuid]} autocomplete="off" />
							<button type="submit" disabled={!(draft[q.uuid] ?? '').trim()}>send</button>
						</form>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.questions {
		display: grid;
		gap: 8px;
		padding: 8px;
		border-bottom: 1px solid var(--line, currentColor);
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 10px;
	}
	.who {
		margin: 0;
		font-size: 0.85em;
		opacity: 0.75;
	}
	.prompt {
		margin: 2px 0 6px;
		overflow-wrap: anywhere;
	}
	form {
		display: flex;
		gap: 6px;
		align-items: center;
	}
	label {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
	}
	input {
		flex: 1;
		min-width: 0;
	}
	.none,
	.result {
		margin: 0;
	}
</style>
