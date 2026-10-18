<!--
  A sequence the model shows (renderers.rs Sequence) as inline SVG at its own size, scrolled
  sideways when wider than the log: sequence/layout.ts places it. Every word is a <text> node;
  every mark (participant, message arrow, note, phase) carries its whole say as a <title>.
  A reply is a dashed arrow, and its title says "(reply)", so dashing is never the only sign.
-->
<script lang="ts">
	import { layoutSequence, type SequenceProps } from './sequence/layout';

	let { sequence }: { sequence: SequenceProps } = $props();

	const arrow = $props.id();
	const g = $derived(layoutSequence(sequence));
	const label = $derived(
		`${sequence.title ? `${sequence.title} — ` : ''}sequence, ${sequence.participants.length} participants and ${sequence.steps.length} steps`
	);
</script>

<div class="sequence">
	<svg viewBox="0 0 {g.W} {g.H}" width={g.W} height={g.H} role="group" aria-label={label}>
		<title>{label}</title>
		<defs>
			<marker id={arrow} viewBox="0 0 8 8" refX="8" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
				<polygon class="head" points="0 0, 8 4, 0 8" />
			</marker>
		</defs>
		{#each g.lifelines as l, i (i)}
			<line class="lifeline" x1={l.x} y1={l.y1} x2={l.x} y2={l.y2} />
		{/each}
		{#each g.actors as a (a.name)}
			<g class="actor">
				<title>{a.name}</title>
				<rect x={a.box.x} y={a.box.y} width={a.box.w} height={a.box.h} rx="4" />
				<text x={a.label.x} y={a.label.y} text-anchor="middle" font-size={g.FONT}>{a.label.t}</text>
			</g>
		{/each}
		{#each g.steps as s (s.i)}
			{#if s.kind === 'message'}
				<path class="msg" class:dashed={s.dashed} d={s.d} marker-end="url(#{arrow})"><title>{s.tip}</title></path>
			{:else if s.kind === 'note'}
				<rect class="note" x={s.rect.x} y={s.rect.y} width={s.rect.w} height={s.rect.h} rx="2"><title>{s.tip}</title></rect>
			{:else}
				<line class="phase" x1={s.rule.x1} y1={s.rule.y} x2={s.rule.x2} y2={s.rule.y}><title>{s.tip}</title></line>
				<rect class="phase-box" x={s.rect.x} y={s.rect.y} width={s.rect.w} height={s.rect.h} rx="2" />
			{/if}
			<text class="label {s.kind}-label" x={s.label.x} y={s.label.y} text-anchor={s.label.anchor} font-size={g.FONT}>{s.label.t}</text>
		{/each}
	</svg>
</div>

<style>
	.sequence {
		overflow-x: auto;
		max-width: 100%;
	}
	svg {
		display: block;
	}
	text {
		font-family: ui-sans-serif, system-ui, sans-serif;
		fill: var(--fg);
	}
	.message-label {
		fill: var(--fg);
	}
	.note-label,
	.phase-label {
		fill: var(--muted);
	}
	.lifeline {
		stroke: var(--glass-brd);
		stroke-dasharray: 2 3;
	}
	.actor rect {
		fill: var(--glass);
		stroke: var(--glass-brd);
	}
	.msg {
		fill: none;
		stroke: var(--muted);
		stroke-width: 1;
	}
	.msg.dashed {
		stroke-dasharray: 4 3;
	}
	.head {
		fill: var(--muted);
	}
	.note {
		fill: var(--glass);
		stroke: var(--warn);
	}
	.phase {
		stroke: var(--glass-brd);
	}
	.phase-box {
		fill: var(--bg, var(--glass));
		stroke: var(--glass-brd);
	}
</style>
