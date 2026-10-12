<!--
  The eye: one lens — metal bezel, dark glass, a glowing core. The core says the state
  by hue, size, brightness and rhythm; the label under it says it in words and is the
  accessible truth (always rendered). Inline SVG + CSS only: no canvas, WebGL or asset.
  Reduced motion stops every keyframe; colour and size still differ per state.
-->
<script lang="ts">
	import { label, type View } from './eye';

	let { view }: { view: View } = $props();
</script>

<div class="eye" data-state={view.state} role="status" aria-live="polite">
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
		<circle class="swirl" cx="50" cy="50" r="22" fill="none" stroke-width="0.8" stroke-dasharray="3 5" />
		<circle class="segment" cx="50" cy="50" r="31" fill="none" stroke-width="2" stroke-linecap="round" stroke-dasharray="24 171" />
		<ellipse cx="38" cy="33" rx="13" ry="7" fill="#fff" opacity="0.08" transform="rotate(-30 38 33)" />
	</svg>
	<p class="label">{label(view)}</p>
</div>

<style>
	.eye {
		--core: #ff2a1a;
		--lvl: 0.55;
		--size: 0.85;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		padding: 8px 0 0;
	}
	svg {
		width: 84px;
		height: 84px;
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
		transition: opacity 300ms, transform 300ms;
	}
	.swirl,
	.segment {
		stroke: var(--core);
		opacity: 0;
		transition: opacity 300ms;
	}
	.label {
		margin: 0;
		font-size: 11px;
		color: var(--muted);
	}

	[data-state='idle'] .core {
		animation: breathe 4s ease-in-out infinite;
	}
	[data-state='listening'] {
		--lvl: 0.85;
		--size: 0.95;
	}
	[data-state='thinking'] {
		--lvl: 0.9;
		--size: 0.95;
	}
	[data-state='thinking'] .core {
		animation: pulse 1.2s ease-in-out infinite;
	}
	[data-state='thinking'] .swirl {
		opacity: 0.6;
		animation: spin 3s linear infinite;
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
	[data-state='waiting'] .label,
	[data-state='refused'] .label {
		color: var(--fg);
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
		.hue {
			animation: none;
			transition: none;
		}
	}
</style>
