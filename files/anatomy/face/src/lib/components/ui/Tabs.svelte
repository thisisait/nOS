<!--
  Tabs — the in-window view switcher.

  WHY THIS IS SHARED, and the argument is correctness rather than DRY. Two
  components had rolled their own tab strip (AnatomyApp, FilePicker) and
  NEITHER was a tablist: one used `aria-current="page"`, which is the attribute
  for the current page in a set of navigation links and says nothing about a
  selected tab; the other had no ARIA at all. Both were keyboard-navigable only
  by Tab-through, so reaching the third view meant three stops instead of one
  arrow key.

  This implements the WAI-ARIA tabs pattern: `role="tablist"`, roving tabindex,
  Left/Right/Home/End, and `aria-selected` on the selected tab.

  Deliberately NOT a router. It owns which tab is selected and nothing else;
  the caller renders the panel. That keeps it usable for a window's views, a
  picker's sources, or anything else, without knowing what any of them are.
-->
<script lang="ts">
	import Icon from './Icon.svelte';
	import Badge from './Badge.svelte';
	import type { Tone } from './tone';

	export interface TabSpec {
		key: string;
		label: string;
		/** Optional text glyph — rendered through Icon, so it is grapheme-safe. */
		icon?: string;
		/** Optional trailing marker, e.g. "thread" or a count's meaning. */
		badge?: string;
		badgeTone?: Tone;
	}

	interface Props {
		tabs: TabSpec[];
		/** Two-way: the caller renders the panel for whatever is selected. */
		active: string;
		/** Names the tablist for assistive tech, e.g. "Anatomy views". */
		label: string;
	}

	let { tabs, active = $bindable(), label }: Props = $props();

	let els: Record<string, HTMLButtonElement | undefined> = {};

	function move(delta: number) {
		const i = tabs.findIndex((t) => t.key === active);
		if (i < 0) return;
		// Wraps. A tab strip is a ring, and stopping at the end is a surprise
		// that costs a keystroke every time.
		const next = tabs[(i + delta + tabs.length) % tabs.length];
		active = next.key;
		els[next.key]?.focus();
	}

	function onkeydown(e: KeyboardEvent) {
		switch (e.key) {
			case 'ArrowRight':
				move(1);
				break;
			case 'ArrowLeft':
				move(-1);
				break;
			case 'Home':
				active = tabs[0].key;
				els[active]?.focus();
				break;
			case 'End':
				active = tabs[tabs.length - 1].key;
				els[active]?.focus();
				break;
			default:
				return;
		}
		e.preventDefault();
	}
</script>

<!-- The keydown lives on the TABS, not on the tablist. In the ARIA pattern the
     tablist is not focusable — the selected tab is, via the roving tabindex —
     so a handler on the container would only ever fire by bubbling, and
     svelte-check is right to flag a listener on a non-focusable role. -->
<div class="tabs" role="tablist" aria-label={label}>
	{#each tabs as t (t.key)}
		<button
			bind:this={els[t.key]}
			class="tab"
			class:on={active === t.key}
			role="tab"
			id="tab-{t.key}"
			aria-selected={active === t.key}
			aria-controls="panel-{t.key}"
			tabindex={active === t.key ? 0 : -1}
			{onkeydown}
			onclick={() => (active = t.key)}
		>
			{#if t.icon}<Icon icon={t.icon} title={t.label} size={14} labelled={false} />{/if}
			{t.label}
			{#if t.badge}<Badge tone={t.badgeTone ?? 'info'} outline>{t.badge}</Badge>{/if}
		</button>
	{/each}
</div>

<style>
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
	/* Keyboard focus must be visible: with a roving tabindex the focused tab is
	   the only way to tell where you are. */
	.tab:focus-visible {
		outline: 2px solid var(--accent, #6aa2ff);
		outline-offset: -2px;
	}
</style>
