/**
 * nOS-face UI primitives — the shell's shared vocabulary for state.
 *
 * This will grow into a small library as more native apps land, and that is
 * fine — the operator called it on 2026-08-05 and removed the count cap that
 * used to guard it. Size was never the risk.
 *
 * THE RULE THAT REPLACED THE COUNT, and it is the one worth keeping: a
 * primitive sits BELOW everything that uses it. It may not import from
 * `$lib/apps/**` or `$lib/anatomy/**`. The moment one does, it stops being a
 * primitive and becomes a feature component in a shared folder — and every app
 * that imports it inherits that feature. Gated by
 * `tests/anatomy/test_face_shell_vocabulary.py`.
 *
 * The bar for adding one is unchanged: the same thing exists in three
 * components with three different spellings. A local component is cheaper than
 * a shared one with four boolean props.
 *
 * See `./tone.ts` for why the four StatusNote kinds are not interchangeable.
 */
export { default as StatusNote } from './StatusNote.svelte';
export { default as Badge } from './Badge.svelte';
export { default as StateDot } from './StateDot.svelte';
export { default as Panel } from './Panel.svelte';
export { default as Tabs, type TabSpec } from './Tabs.svelte';
export { default as Icon } from './Icon.svelte';
export { graphemes, clampGlyphs, monogram, appGlyph } from './glyph';
export { MOTION, duration, prefersReducedMotion } from './motion';
export {
	TONES,
	STATUS_KINDS,
	STATUS_TONE,
	STATUS_GLYPH,
	toneVars,
	exitTone,
	severityTone,
	type Tone,
	type StatusKind
} from './tone';
