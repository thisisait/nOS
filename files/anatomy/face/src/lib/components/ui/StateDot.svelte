<!--
  StateDot — the row-leading severity marker.

  Carries an accessible label, because a colour alone is not a signal: a
  red/green dot conveys nothing to a screen reader and little to the ~8% of
  men with a red-green deficiency. The label is what the dot MEANS, not its
  colour, so callers pass "failing", never "red".
-->
<script lang="ts">
	import { toneVars, type Tone } from './tone';

	interface Props {
		tone?: Tone;
		/** What the dot means, e.g. "failing", "never ran". Announced, not shown. */
		label: string;
	}

	let { tone = 'neutral', label }: Props = $props();
	const vars = $derived(toneVars(tone));
</script>

<span class="dot" style="--solid: {vars.solid}" role="img" aria-label={label} title={label}></span>

<style>
	.dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
		background: var(--solid);
	}
</style>
