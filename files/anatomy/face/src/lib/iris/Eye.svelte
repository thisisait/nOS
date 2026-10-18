<!--
  The eye: one lens — metal bezel, dark glass, a glowing core. The core says the state
  by hue, size, brightness and rhythm; the speech bubble beside it says the mood in words
  (the accessible truth, always rendered), coloured per mood, with a small moving icon.
  Inline SVG + CSS only. Reduced motion stops every keyframe; colour and text still differ.
-->
<script lang="ts">
	import { mood, type View } from './eye';

	let { view }: { view: View } = $props();
	const m = $derived(mood(view));
</script>

<div class="eye" data-state={view.state}>
	<svg viewBox="0 0 100 100" aria-hidden="true">
		<defs>
			<radialGradient id="eye-bezel" cx="40%" cy="35%" r="70%">
				<stop offset="0%" stop-color="#5b6068" />
				<stop offset="60%" stop-color="#26292e" />
				<stop offset="100%" stop-color="#0e0f11" />
			</radialGradient>
			<radialGradient id="eye-glass" cx="50%" cy="50%" r="50%">
				<stop offset="0%" stop-color="#1a0606" />
				<stop offset="100%" stop-color="#050506" />
			</radialGradient>
			<radialGradient id="eye-core" cx="50%" cy="50%" r="50%">
				<stop offset="0%" class="hot" />
				<stop offset="35%" class="hue" />
				<stop offset="100%" class="hue" stop-opacity="0" />
			</radialGradient>
			<filter id="eye-glow" x="-50%" y="-50%" width="200%" height="200%">
				<feGaussianBlur stdDeviation="3" />
			</filter>
		</defs>
		<circle cx="50" cy="50" r="49" fill="url(#eye-bezel)" />
		<circle cx="50" cy="50" r="43" fill="none" stroke="#0a0b0c" stroke-width="2" />
		<circle cx="50" cy="50" r="40" fill="none" stroke="#3d4148" stroke-width="0.8" />
		<circle cx="50" cy="50" r="38" fill="url(#eye-glass)" />
		<g class="core">
			<circle cx="50" cy="50" r="26" fill="url(#eye-core)" filter="url(#eye-glow)" />
			<circle cx="50" cy="50" r="15" fill="url(#eye-core)" />
		</g>
		<circle
			class="swirl"
			cx="50"
			cy="50"
			r="22"
			fill="none"
			stroke-width="0.8"
			stroke-dasharray="3 5"
		/>
		<circle
			class="segment"
			cx="50"
			cy="50"
			r="31"
			fill="none"
			stroke-width="2"
			stroke-linecap="round"
			stroke-dasharray="24 171"
		/>
		<ellipse
			cx="38"
			cy="33"
			rx="13"
			ry="7"
			fill="#fff"
			opacity="0.08"
			transform="rotate(-30 38 33)"
		/>
	</svg>
	<div class="bubble" data-mood={m.key} role="status" aria-live="polite">
		<!-- Keyed: a new mood remounts the words, so the pop plays on every change. -->
		{#key m.key + m.text}
			<span class="say">
				{#if m.icon}<span class="icon" aria-hidden="true">{m.icon}</span>{/if}{m.text}
			</span>
		{/key}
	</div>
</div>

<style>
	.eye {
		--core: #ff2a1a;
		--lvl: 0.55;
		--size: 0.85;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 12px;
		padding: 6px 0 0;
	}
	svg {
		flex: none;
		width: 64px;
		height: 64px;
	}
	.hot {
		stop-color: #fff3e8;
	}
	.hue {
		stop-color: var(--core);
		transition: stop-color 300ms;
	}
	.core,
	.swirl,
	.segment {
		transform-box: view-box;
		transform-origin: 50px 50px;
	}
	.core {
		opacity: var(--lvl);
		transform: scale(var(--size));
		transition:
			opacity 300ms,
			transform 300ms;
	}
	.swirl,
	.segment {
		stroke: var(--core);
		opacity: 0;
		transition: opacity 300ms;
	}
	/* The comic bubble: an opaque mix of a token over the canvas, so the tail (a rotated
	   square of the same colour) does not show a seam where it overlaps the box. */
	.bubble {
		--tone: var(--muted);
		position: relative;
		min-width: 0;
		padding: 5px 10px;
		border-radius: 12px;
		background: color-mix(in srgb, var(--tone) 26%, var(--bg));
		color: var(--fg);
		font-size: 12px;
		line-height: 1.3;
		transition: background-color 300ms;
	}
	.bubble::before {
		content: '';
		position: absolute;
		left: -4px;
		top: 50%;
		width: 9px;
		height: 9px;
		background: inherit;
		transform: translateY(-50%) rotate(45deg);
		border-radius: 1px;
	}
	.say {
		position: relative;
		display: inline-flex;
		align-items: center;
		gap: 5px;
		overflow-wrap: anywhere;
		animation: pop 260ms ease-out;
	}
	.icon {
		display: inline-block;
	}
	/* Neutral at rest, blue while the model works in its head, cyan when it reaches out
	   with a tool, amber when it is the person's turn, red on a refusal. */
	[data-mood='ready'],
	[data-mood='listening'] {
		--tone: var(--fg);
	}
	[data-mood='thinking'],
	[data-mood='writing'],
	[data-mood='said'] {
		--tone: var(--info);
	}
	[data-mood='working'] {
		--tone: var(--ok);
	}
	[data-mood='waiting'] {
		--tone: var(--warn);
	}
	[data-mood='refused'] {
		--tone: var(--bad);
	}
	[data-mood='offline'] {
		--tone: var(--glass-brd);
		color: var(--muted);
	}
	[data-mood='thinking'] .icon {
		animation: think 1s ease-in-out infinite;
	}
	[data-mood='working'] .icon {
		transform-origin: 20% 80%;
		animation: swing 0.7s ease-in-out infinite;
	}
	[data-mood='asleep'] .icon {
		animation: drift 2.6s ease-in-out infinite;
	}
	[data-mood='ready'] .icon {
		transform-origin: 50% 90%;
		animation: nod 900ms ease-out 1;
	}
	[data-mood='waiting'] .icon {
		animation: think 1.6s ease-in-out infinite;
	}

	[data-state='idle'] .core {
		animation: breathe 4s ease-in-out infinite;
	}
	[data-state='listening'] {
		--lvl: 0.85;
		--size: 0.95;
	}
	/* Thinking is the state people miss: a deep fast throb, the swirl spinning one way
	   and the segment the other, so the lens is never still while the model works. */
	[data-state='thinking'] {
		--lvl: 1;
		--size: 1;
	}
	[data-state='thinking'] .core {
		animation: throb 0.9s ease-in-out infinite;
	}
	[data-state='thinking'] .swirl {
		opacity: 1;
		stroke-width: 1.6;
		animation: spin 1.4s linear infinite;
	}
	[data-state='thinking'] .segment {
		opacity: 0.8;
		animation: spin 2.2s linear infinite reverse;
	}
	[data-state='tool'] {
		--lvl: 0.85;
		--size: 0.9;
	}
	[data-state='tool'] .segment {
		opacity: 0.9;
		animation: spin 1.2s linear infinite;
	}
	[data-state='writing'] {
		--lvl: 1;
		--size: 1;
	}
	[data-state='writing'] .core {
		animation: pulse 0.6s ease-in-out infinite;
	}
	[data-state='waiting'] {
		--core: #ffb020;
		--lvl: 0.9;
		--size: 0.95;
	}
	[data-state='waiting'] .core {
		animation: pulse 2.4s ease-in-out infinite;
	}
	[data-state='said'] {
		--lvl: 1;
		--size: 1;
	}
	[data-state='said'] .core {
		animation: flash 600ms ease-out 1;
	}
	[data-state='refused'] {
		--lvl: 0.7;
	}
	[data-state='refused'] .core {
		animation: flicker 1.5s steps(1) 1;
	}
	[data-state='disconnected'] {
		--core: #5c5c5c;
		--lvl: 0.18;
		--size: 0.7;
	}

	@keyframes breathe {
		50% {
			opacity: calc(var(--lvl) * 0.6);
			transform: scale(calc(var(--size) * 0.92));
		}
	}
	@keyframes pulse {
		50% {
			opacity: calc(var(--lvl) * 0.65);
			transform: scale(calc(var(--size) * 0.9));
		}
	}
	@keyframes throb {
		50% {
			opacity: calc(var(--lvl) * 0.3);
			transform: scale(calc(var(--size) * 0.72));
		}
	}
	@keyframes pop {
		from {
			opacity: 0;
			transform: scale(0.8);
		}
	}
	@keyframes think {
		50% {
			transform: scale(1.25);
		}
	}
	@keyframes swing {
		0%,
		100% {
			transform: rotate(20deg);
		}
		50% {
			transform: rotate(-35deg);
		}
	}
	@keyframes drift {
		0%,
		100% {
			opacity: 1;
			transform: translate(0, 0);
		}
		50% {
			opacity: 0.45;
			transform: translate(2px, -3px);
		}
	}
	@keyframes nod {
		40% {
			transform: rotate(-12deg);
		}
	}
	@keyframes flash {
		0% {
			opacity: 1;
			transform: scale(1.15);
		}
	}
	@keyframes flicker {
		0%,
		20%,
		40% {
			opacity: 0.15;
		}
		10%,
		30%,
		50% {
			opacity: 1;
		}
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.core,
		.swirl,
		.segment,
		.hue,
		.bubble,
		.say,
		.icon {
			animation: none;
			transition: none;
		}
	}
</style>
