<!--
  Anatomy — one app, three views of the same organism (Pulse / Wing / Bone).

  ONE app rather than three, decided 2026-08-04: a pulse run, a wing event and
  a bone action share an `actor_action_id` and are one story. Three windows
  lose the thread the operator is actually following.

  THE SHELL OWNS exactly two things: which view is selected, and the THREAD —
  an `actor_action_id` a view can hand it, which the Wing view then narrows to.
  It owns no data; each view fetches its own. That is what keeps a view
  replaceable without touching this file.

  Read-only throughout. Actions stay in Wing UI, where the RBAC gates are.
-->
<script lang="ts">
	import PulseView from './PulseView.svelte';
	import WingView from './WingView.svelte';
	import BoneView from './BoneView.svelte';
	import { Badge } from '$lib/components/ui';

	type ViewKey = 'pulse' | 'wing' | 'bone';

	const VIEWS: Array<{ key: ViewKey; label: string; icon: string }> = [
		{ key: 'pulse', label: 'Pulse', icon: '⏱' },
		{ key: 'wing', label: 'Wing', icon: '🪶' },
		{ key: 'bone', label: 'Bone', icon: '🦴' }
	];

	let active = $state<ViewKey>('pulse');

	/** The cross-view thread. A run in the Pulse view hands its actor_action_id
	 *  up; the shell switches to Wing and passes it down. Nothing else in the
	 *  shell knows what the value means — it is an opaque key here. */
	let thread = $state('');

	function follow(actionId: string) {
		thread = actionId;
		active = 'wing';
	}
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
				{#if v.key === 'wing' && thread}
					<Badge tone="info" outline>thread</Badge>
				{/if}
			</button>
		{/each}
	</nav>

	<div class="body">
		{#if active === 'pulse'}
			<PulseView onfollowthread={follow} />
		{:else if active === 'wing'}
			<WingView {thread} onclearthread={() => (thread = '')} />
		{:else}
			<BoneView />
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
	.body {
		flex: 1;
		min-height: 0;
		overflow: auto;
		padding-top: 10px;
	}
</style>
