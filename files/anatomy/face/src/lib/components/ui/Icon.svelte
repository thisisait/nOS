<!--
  Icon — one place that turns an operator-authored glyph into something safe
  to render.

  The face has no icon font (it is a deliberate constraint: an offline-first
  shell should not depend on a webfont), so every icon in the estate is a text
  glyph — emoji from a plugin manifest, a geometric mark from `layouts.ts`, or
  a monogram derived from the title. Three call sites derived that three
  different ways, and one of them produced mojibake for a two-emoji icon.

  Always renders escaped text. There is no HTML path here by design: icons
  arrive from operator-authored `hub_card` blocks, which is untrusted input.
-->
<script lang="ts">
	import { appGlyph } from './glyph';

	interface Props {
		/** Operator-authored glyph. Empty/absent → a monogram of the title. */
		icon?: string;
		/** Used for the monogram fallback AND as the accessible name. */
		title: string;
		/** Max whole graphemes to show. Never cuts inside one. */
		max?: number;
		/** px. The dock wants big, a row wants small. */
		size?: number;
		/** Set false when an adjacent element already names the thing — a
		 *  duplicate announcement is noise for a screen reader. */
		labelled?: boolean;
	}

	let { icon = '', title, max = 2, size = 16, labelled = true }: Props = $props();

	const glyph = $derived(appGlyph(icon, title, max));
</script>

<span
	class="icon"
	style="font-size: {size}px"
	role={labelled ? 'img' : undefined}
	aria-label={labelled ? title : undefined}
	aria-hidden={labelled ? undefined : 'true'}>{glyph}</span
>

<style>
	.icon {
		display: inline-block;
		line-height: 1;
		font-variant-emoji: emoji;
		/* Keep an emoji from inheriting a UI font that would render it as a
		   monochrome outline on some platforms. */
		font-family: 'Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji', system-ui, sans-serif;
	}
</style>
