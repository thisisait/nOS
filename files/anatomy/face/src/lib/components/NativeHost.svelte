<!--
  NativeHost — stable renderer for a native (API-calling, non-iframe) app.

  Why this exists: rendering `{#await resolveNativeComponent(win.app) then C}`
  INLINE in the desktop `{#each}` re-created the promise on every store update
  (focusWindow on pointerdown, moves, z-changes…), so `{#await}` tore down and
  remounted the app on every interaction — losing the in-flight click and
  resetting the app's state (the "Files clicks do nothing / always documents"
  bug). Here the component is resolved ONCE per app slug into stable local
  state, so parent re-renders never remount the app.
-->
<script lang="ts">
	import type { Component } from 'svelte';
	import { resolveNativeComponent } from '$lib/apps/native';

	let { app }: { app: string } = $props();

	let Comp = $state<Component | null>(null);
	let failed = $state(false);

	// Resolve once per app slug. `app` is stable for a window's lifetime, so this
	// effect runs a single time; it never re-imports on unrelated store updates.
	// We intentionally do NOT reset `Comp = null` on (re-)run: were the effect ever
	// re-evaluated, nulling Comp would unmount + remount the child app (losing its
	// state + the in-flight click). Resolving to the same cached module is a no-op.
	$effect(() => {
		let cancelled = false;
		const p = resolveNativeComponent(app);
		if (!p) {
			failed = true;
			return;
		}
		p.then((c) => {
			if (!cancelled) Comp = c;
		}).catch(() => {
			if (!cancelled) failed = true;
		});
		return () => {
			cancelled = true;
		};
	});
</script>

{#if Comp}
	<Comp />
{:else if failed}
	<p class="muted">This app could not be loaded.</p>
{:else}
	<p class="muted">Loading…</p>
{/if}

<style>
	.muted {
		color: var(--muted);
	}
</style>
