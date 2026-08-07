<!--
  WidgetHost — stable renderer for one registered widget.

  Same reason `NativeHost` exists, and the same bug it was written to kill:
  resolving `{#await resolveNativeComponent(slug)}` INLINE re-creates the
  promise on every parent re-render, so the component tears down and remounts
  and any in-flight click is lost. The component is resolved ONCE into stable
  local state here.

  A widget that fails to load says so. It does NOT render an empty box: an
  empty corner of the desktop is indistinguishable from a widget with nothing
  to report, and those are different facts.
-->
<script lang="ts">
	import type { Component } from 'svelte';
	import { resolveNativeComponent } from '$lib/apps/native';
	import type { Identity } from '$lib/contracts';

	let { slug, identity }: { slug: string; identity?: Identity } = $props();

	let Comp = $state<Component<{ identity?: Identity }> | null>(null);
	let failed = $state(false);

	$effect(() => {
		let cancelled = false;
		const p = resolveNativeComponent(slug);
		if (!p) {
			failed = true;
			return;
		}
		p.then((c) => {
			if (!cancelled) Comp = c as Component<{ identity?: Identity }>;
		}).catch(() => {
			if (!cancelled) failed = true;
		});
		return () => {
			cancelled = true;
		};
	});
</script>

{#if Comp}
	<Comp {identity} />
{:else if failed}
	<p class="failed glass">The “{slug}” widget could not be loaded.</p>
{/if}

<style>
	.failed {
		margin: 0;
		padding: 8px 10px;
		font-size: 12px;
		color: var(--bad-ink);
		background: var(--bad-soft);
		pointer-events: auto;
	}
</style>
