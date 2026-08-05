<!--
  Anatomy — one app, three views of the same organism (Pulse / Wing / Bone).

  ONE app rather than three, decided 2026-08-04: a pulse run, a wing event and a
  bone action share an `actor_action_id` and are one story. Three windows lose
  the thread the operator is actually following.

  THE SHELL OWNS: the tab strip, which view is selected, and the convention that
  an unbuilt view says so. It owns NO data — each view fetches its own. That is
  what lets the Wing and Bone views be added by dropping a component in beside
  PulseView and adding a line to VIEWS, without editing anything here.

  Read-only. Actions stay in Wing UI, where the RBAC gates already are.
-->
<script lang="ts">
	import PulseView from './PulseView.svelte';

	type ViewKey = 'pulse' | 'wing' | 'bone';

	const VIEWS: Array<{ key: ViewKey; label: string; icon: string; built: boolean }> = [
		{ key: 'pulse', label: 'Pulse', icon: '⏱', built: true },
		{ key: 'wing', label: 'Wing', icon: '🪶', built: false },
		{ key: 'bone', label: 'Bone', icon: '🦴', built: false }
	];

	let active = $state<ViewKey>('pulse');
</script>

<div class="anatomy">
	<nav class="tabs" aria-label="Anatomy views">
		{#each VIEWS as v (v.key)}
			<button
				class="tab"
				class:on={active === v.key}
				aria-current={active === v.key ? 'page' : undefined}
				onclick={() => (active = v.key)}
			>
				<span class="ic" aria-hidden="true">{v.icon}</span>{v.label}
				{#if !v.built}<span class="soon">not built</span>{/if}
			</button>
		{/each}
	</nav>

	<div class="body">
		{#if active === 'pulse'}
			<PulseView />
		{:else}
			<!--
				An explicit unbuilt state, NOT an empty panel. A blank pane in an
				observability app reads as "nothing is happening", which is the exact
				misreading this whole app exists to prevent.
			-->
			<div class="unbuilt">
				<p class="h">The {VIEWS.find((v) => v.key === active)?.label} view is not built yet.</p>
				<p>
					This pane is empty because nobody has written it — not because the organ is idle.
					Until it exists, use Wing UI for {active === 'wing' ? 'events and the timeline' : 'Bone actions and audit lineage'}.
				</p>
			</div>
		{/if}
	</div>
</div>

<style>
	.anatomy {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
	}
	.tabs {
		display: flex;
		gap: 4px;
		padding-bottom: 8px;
		border-bottom: 1px solid var(--glass-brd, rgba(255, 255, 255, 0.1));
		flex-shrink: 0;
	}
	.tab {
		display: flex;
		align-items: center;
		gap: 6px;
		background: none;
		border: none;
		color: var(--muted, #9aa4b2);
		padding: 6px 12px;
		border-radius: 8px;
		font-size: 13px;
		cursor: pointer;
	}
	.tab:hover {
		background: rgba(255, 255, 255, 0.06);
	}
	.tab.on {
		background: rgba(255, 255, 255, 0.1);
		color: var(--fg, #e8ecf3);
	}
	.ic {
		font-size: 14px;
	}
	.soon {
		font-size: 9px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		opacity: 0.6;
		border: 1px solid currentColor;
		border-radius: 4px;
		padding: 0 4px;
	}
	.body {
		flex: 1;
		min-height: 0;
		overflow: auto;
		padding-top: 10px;
	}
	.unbuilt {
		max-width: 46ch;
		margin: 32px auto;
		text-align: center;
		color: var(--muted, #9aa4b2);
		font-size: 13px;
		line-height: 1.6;
	}
	.unbuilt .h {
		color: var(--fg, #e8ecf3);
		font-weight: 600;
	}
</style>
