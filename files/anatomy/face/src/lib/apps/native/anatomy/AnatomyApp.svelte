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
	import { Tabs, type TabSpec } from '$lib/components/ui';

	type ViewKey = 'pulse' | 'wing' | 'bone';

	let active = $state<ViewKey>('pulse');

	/** The cross-view thread. A run in the Pulse view hands its actor_action_id
	 *  up; the shell switches to Wing and passes it down. Nothing else in the
	 *  shell knows what the value means — it is an opaque key here. */
	let thread = $state('');

	function follow(actionId: string) {
		thread = actionId;
		active = 'wing';
	}

	// The badge is derived, so the tab strip shows a thread is pinned even when
	// the operator has switched away from Wing to check something else.
	const tabs = $derived<TabSpec[]>([
		{ key: 'pulse', label: 'Pulse', icon: '⏱' },
		{ key: 'wing', label: 'Wing', icon: '🪶', badge: thread ? 'thread' : undefined },
		{ key: 'bone', label: 'Bone', icon: '🦴' }
	]);
</script>

<div class="anatomy">
	<Tabs {tabs} bind:active label="Anatomy views" />

	<div class="body" role="tabpanel" id="panel-{active}" aria-labelledby="tab-{active}">
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
	/* The tab strip's rules moved to $lib/components/ui/Tabs.svelte, which is
	   also where it became an actual ARIA tablist — this one used
	   aria-current="page", the attribute for navigation links. */
	.body {
		flex: 1;
		min-height: 0;
		overflow: auto;
		padding-top: 10px;
	}
</style>
