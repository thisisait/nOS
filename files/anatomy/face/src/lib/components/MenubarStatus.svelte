<!--
  Menubar status — the always-visible half of Anatomy.

  A desktop's menubar is the only surface a user never has to open, so it is
  where ambient awareness belongs. Clicking a chip opens the Anatomy window on
  the view that answers it, which is the whole relationship: the bar says THAT
  something is wrong, the app says WHAT.

  When there is nothing to report the bar shows a small neutral dot, not a
  green tick. A tick is a claim of health; this is a claim of silence, and the
  two are not the same thing — a container reported healthy to Docker for ten
  days while serving its own installer, and every signal the operator had was
  green. The tooltip says so in as many words.

  Live for Tier-1 only. Everyone else gets `visible: false` and renders nothing
  at all — not an error, not a placeholder.
-->
<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { bffGet } from '$lib/api/client';
	import { chips, QUIET, type SystemStatus } from '$lib/anatomy/status';
	import { Badge, StateDot } from '$lib/components/ui';

	interface Props {
		/** Opens the Anatomy app on a given view. Supplied by the desktop root. */
		onopen?: (view: 'pulse' | 'wing' | 'bone') => void;
	}
	let { onopen }: Props = $props();

	let status = $state<SystemStatus>(QUIET);

	// 60s, matching the Anatomy views. The underlying data changes on a cron;
	// polling faster would re-render the same numbers at the user's expense.
	const POLL_MS = 60_000;
	let timer: ReturnType<typeof setInterval> | undefined;

	async function refresh() {
		try {
			status = await bffGet<SystemStatus>('/bff/status');
		} catch {
			// A failed poll must not blank a bar that was showing real counts —
			// that would read as "the problem went away". Keep the last known
			// state; the next tick corrects it.
		}
	}

	onMount(() => {
		void refresh();
		timer = setInterval(() => void refresh(), POLL_MS);
		// Re-check on focus: a laptop that slept for four hours should not show
		// four-hour-old counts until the next tick happens to fire.
		const onVisible = () => {
			if (document.visibilityState === 'visible') void refresh();
		};
		document.addEventListener('visibilitychange', onVisible);
		return () => document.removeEventListener('visibilitychange', onVisible);
	});
	onDestroy(() => clearInterval(timer));

	const list = $derived(chips(status));
</script>

{#if status.visible}
	<div class="status">
		{#if list.length === 0}
			<button
				class="quiet"
				onclick={() => onopen?.('pulse')}
				title="Nothing to report. That is not the same as verified healthy — it means no failing, overdue or never-run job and no unread alert was found in the last check."
			>
				<StateDot tone="neutral" label="nothing to report" />
			</button>
		{:else}
			{#each list as c (c.key)}
				<button class="chip" onclick={() => onopen?.(c.view)} title={c.title}>
					<Badge tone={c.tone} count={c.count}>&nbsp;{c.label}</Badge>
				</button>
			{/each}
		{/if}
	</div>
{/if}

<style>
	.status {
		display: flex;
		align-items: center;
		gap: 6px;
		/* The menubar is click-through so window titlebars underneath stay
		   draggable; the chips have to opt back in. */
		pointer-events: auto;
	}
	button {
		background: none;
		border: none;
		padding: 0;
		display: flex;
		align-items: center;
		cursor: pointer;
	}
	.quiet {
		opacity: 0.5;
	}
	.quiet:hover {
		opacity: 1;
	}
	.chip:hover {
		filter: brightness(1.25);
	}
</style>
