<!--
  Modal — THE overlay surface. One scrim, one panel, one set of manners.

  WHY: the tables editor hand-rolled its own fixed-center wrapper with a
  460px cap and a 52vh inner scroll — on a small window it overflowed the
  desktop, on a large one it wasted it, and every future detail view was
  about to copy the same wrapper a third way (operator, 2026-09-23:
  "modály přetékají mimo okno, je potřeba scroll a je velmi úzký").

  Manners, owned here so no caller re-implements them:
  - width by `size` (md 520 / lg 780 / xl 1100), always clamped to 94vw;
  - the PANEL clamps to 88vh and the BODY scrolls — header and footer
    stay put, content never pushes the close button off-screen;
  - Escape closes, scrim click closes, ✕ closes — all through `onclose`;
  - role="dialog" + aria-modal + labelled by its own title; the panel takes
    focus on mount so Escape works without a click first;
  - motion respects prefers-reduced-motion (CSS-gated, no JS).

  A primitive: imports nothing from $lib/apps/** or $lib/anatomy/**.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		onclose: () => void;
		size?: 'md' | 'lg' | 'xl';
		/** Sticky action row under the scrolling body (buttons, verdicts). */
		footer?: Snippet;
		children?: Snippet;
	}
	const { title, onclose, size = 'md', footer, children }: Props = $props();

	function onkeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.stopPropagation();
			onclose();
		}
	}

	function takeFocus(node: HTMLElement) {
		node.focus();
	}
</script>

<div class="scrim" role="presentation" onclick={onclose}></div>
<div
	class="panel glass {size}"
	role="dialog"
	aria-modal="true"
	aria-label={title}
	tabindex="-1"
	use:takeFocus
	{onkeydown}
>
	<header>
		<strong>{title}</strong>
		<button class="x" type="button" aria-label="Close" onclick={onclose}>✕</button>
	</header>
	<div class="mbody">
		{@render children?.()}
	</div>
	{#if footer}
		<footer>
			{@render footer()}
		</footer>
	{/if}
</div>

<style>
	.scrim {
		position: fixed;
		inset: 0;
		z-index: 200000;
		background: rgba(0, 0, 0, 0.4);
	}
	.panel {
		position: fixed;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		z-index: 200001;
		display: flex;
		flex-direction: column;
		max-height: 88vh;
		border-radius: 12px;
		font-size: 13px;
		outline: none;
	}
	.panel.md {
		width: min(520px, 94vw);
	}
	.panel.lg {
		width: min(780px, 94vw);
	}
	.panel.xl {
		width: min(1100px, 94vw);
	}
	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		padding: 12px 14px;
		border-bottom: 1px solid rgba(128, 128, 128, 0.25);
		flex: 0 0 auto;
	}
	.x {
		background: none;
		border: none;
		color: var(--muted, #9aa4b2);
		cursor: pointer;
		font-size: 13px;
	}
	.mbody {
		padding: 12px 14px;
		overflow: auto;
		min-height: 0;
		flex: 1 1 auto;
	}
	footer {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 10px 14px;
		border-top: 1px solid rgba(128, 128, 128, 0.25);
		flex: 0 0 auto;
	}
	@media (prefers-reduced-motion: no-preference) {
		.panel {
			animation: modal-in 120ms ease-out;
		}
		@keyframes modal-in {
			from {
				opacity: 0;
				transform: translate(-50%, -49%) scale(0.98);
			}
			to {
				opacity: 1;
				transform: translate(-50%, -50%) scale(1);
			}
		}
	}
</style>
