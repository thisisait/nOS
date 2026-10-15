<!--
  The oldest waiting approval, pinned above the composer. Approve stays disabled until
  the sentinel after the edit's last row has been fully in view: the GUI form of
  shell.rs shown_whole. Reject never needs it.
-->
<script lang="ts">
	import ComponentView from './Component.svelte';
	import type { Decision, Waiting } from './approvals';

	let { waiting, of, whole, onseen, ondecide }: {
		waiting: Waiting;
		of: number;
		whole: boolean;
		onseen: (approval: string) => void;
		ondecide: (approval: string, d: Decision) => void;
	} = $props();
	let end: HTMLElement | undefined = $state();

	$effect(() => {
		const id = waiting.approval;
		if (!end) return;
		const io = new IntersectionObserver((es) => es.some((e) => e.isIntersecting) && onseen(id), { threshold: 1 });
		io.observe(end);
		return () => io.disconnect();
	});
</script>

<section class="card" data-approval={waiting.approval}>
	<div class="edit">
		<p class="head">approval {waiting.approval}{of > 1 ? ` (1 of ${of})` : ''}</p>
		<ComponentView component={waiting.component} />
		<div class="end" bind:this={end} aria-hidden="true"></div>
	</div>
	<div class="ask">
		{#if waiting.component.kind === 'row_diff_approval' && waiting.component.props.op === 'delete'}
			<span class="bad">{whole ? 'approve deleting this row?' : 'scroll to the end to approve deleting this row, or reject it'}</span>
		{:else}
			<span>{whole ? 'approve this edit?' : 'scroll to the end of the edit to approve it, or reject it'}</span>
		{/if}
		<button disabled={!whole} onclick={() => ondecide(waiting.approval, 'approve')}>approve</button>
		<button onclick={() => ondecide(waiting.approval, 'reject')}>reject</button>
	</div>
</section>

<style>
	.card {
		margin: 0 16px;
		border: 1px solid var(--warn-ink);
		border-radius: 12px;
		background: var(--glass);
	}
	.edit {
		max-height: 45vh;
		overflow-y: auto;
		padding: 8px;
	}
	.head {
		margin: 0 0 6px;
		font-size: 11px;
		color: var(--muted);
	}
	.end {
		height: 1px;
	}
	.ask {
		display: flex;
		gap: 8px;
		align-items: center;
		padding: 8px;
		font-weight: 600;
	}
	.ask span {
		flex: 1;
	}
	.ask .bad {
		color: var(--bad-ink);
	}
	button {
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
