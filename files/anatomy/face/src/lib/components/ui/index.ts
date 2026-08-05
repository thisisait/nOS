/**
 * nOS-face UI primitives — the shell's shared vocabulary for state.
 *
 * Deliberately SMALL. These are not a component library; they are the three
 * things that were being re-implemented in every app, plus the type that makes
 * them agree. Anything that belongs to one screen stays on that screen.
 *
 * Adding one here is a decision with a bar: it earns a place when the same
 * thing exists in three components with three different spellings. Until then
 * a local component is cheaper than a shared one with four boolean props.
 *
 * See `./tone.ts` for why the four StatusNote kinds are not interchangeable.
 */
export { default as StatusNote } from './StatusNote.svelte';
export { default as Badge } from './Badge.svelte';
export { default as StateDot } from './StateDot.svelte';
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
