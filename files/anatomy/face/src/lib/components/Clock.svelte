<!--
  Menubar clock.

  Ticks on the minute rather than every second: a second hand in a menubar is
  60× the re-renders for information nobody reads, and on a laptop that is
  measurable battery. The first timeout aligns to the next minute boundary so
  the display never sits a stale 59 seconds behind.

  `datetime` carries the machine-readable value for assistive tech; the visible
  text is the operator's locale, because a self-hosted box in Czechia should
  not show a US date because a library defaulted to one.
-->
<script lang="ts">
	import { onMount, onDestroy } from 'svelte';

	let now = $state(new Date());
	let timer: ReturnType<typeof setTimeout> | undefined;

	function schedule() {
		const ms = 60_000 - ((Date.now() % 60_000) + 1);
		timer = setTimeout(
			() => {
				now = new Date();
				schedule();
			},
			Math.max(1000, ms)
		);
	}

	onMount(() => {
		now = new Date();
		schedule();
	});
	onDestroy(() => clearTimeout(timer));

	const time = $derived(now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }));
	const date = $derived(
		now.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
	);
</script>

<time class="clock" datetime={now.toISOString()} title={now.toString()}>
	<span class="d">{date}</span>
	<span class="t">{time}</span>
</time>

<style>
	.clock {
		display: flex;
		align-items: baseline;
		gap: 8px;
		font-variant-numeric: tabular-nums;
		color: var(--fg);
		white-space: nowrap;
	}
	.d {
		color: var(--muted);
		font-size: 12px;
	}
</style>
