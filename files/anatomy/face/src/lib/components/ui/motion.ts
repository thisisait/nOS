/**
 * The shell's motion vocabulary. ~40 lines, no dependency, no GPU.
 *
 * ── WHY NOT CANVAS UI (canvasui.dev), evaluated 2026-08-05 ──────────────────
 *
 * It is genuinely good work — 33 WebGL/canvas effects, a real Svelte build, GPU
 * animation outside the framework's render cycle, and it respects
 * prefers-reduced-motion. Three things make it the wrong dependency HERE, and
 * only the first is decisive:
 *
 * 1. LICENSE. MIT **+ Commons Clause**, whose restriction is on "reselling or
 *    redistributing the components themselves, whether alone, in a bundle, or
 *    as a port". Canvas UI installs by COPYING SOURCE into the consuming repo
 *    (the shadcn model). nOS is MIT, public, and its entire pitch is a
 *    replicable open-source reference implementation — every clone of this
 *    repository redistributes whatever is vendored into it, in a bundle. That
 *    is the exact act the clause names. Commons Clause is also not an
 *    OSI-approved licence, so vendoring it would make "every component is FOSS"
 *    false for the first time.
 *
 * 2. THE HEADLINE FEATURE NEEDS A CHROME FLAG. The thing that makes Canvas UI
 *    special is real HTML rendered *inside* a canvas with shaders over it, and
 *    that relies on browser capabilities currently behind an experimental flag
 *    in Chrome only. The face is a desktop shell an operator opens in whatever
 *    browser is to hand; an effect that exists in one browser behind a flag is
 *    an effect that does not exist.
 *
 * 3. COST WITHOUT A CLAIM. A WebGL context per window, on a machine already
 *    running ~50 containers, spends GPU and battery to make a status panel
 *    prettier. This shell's job is to tell an operator the truth about their
 *    estate; motion here should direct attention, not decorate.
 *
 * WHAT IS WORTH TAKING is the discipline rather than the code: motion that
 * carries meaning, and a reduced-motion path that is real rather than a
 * courtesy. Both are below, in CSS.
 *
 * ── THE RULE ────────────────────────────────────────────────────────────────
 *
 * Motion in this shell means one of exactly two things:
 *
 *   ORIENTATION — where did this window come from, where did it go. Fast
 *   (≤180ms), spatial, and it never delays interaction.
 *
 *   ATTENTION — something changed that you did not cause. Used sparingly and
 *   ONLY for a transition into a worse state; a thing that starts failing may
 *   pulse once, a thing that recovers may not. Celebration animations train
 *   people to enjoy the dashboard rather than read it.
 *
 * Anything that is neither is decoration, and decoration in an observability
 * surface competes with the signal it is decorating.
 */

/** Durations, in ms. Named so a component cannot invent its own tempo. */
export const MOTION = {
	/** Window open/close/minimise. Short enough to feel immediate. */
	orient: 160,
	/** Attention pulse — one cycle, long enough to notice, not to annoy. */
	attention: 900
} as const;

/**
 * True when the user has asked for less motion.
 *
 * Checked at CALL TIME, not cached at import: the preference can change while
 * the page is open (macOS System Settings toggles it live), and a shell that
 * only reads it once starts animating at someone who has just asked it not to.
 */
export function prefersReducedMotion(): boolean {
	if (typeof window === 'undefined' || !window.matchMedia) return false;
	return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** A duration that collapses to 0 under reduced motion. */
export function duration(kind: keyof typeof MOTION): number {
	return prefersReducedMotion() ? 0 : MOTION[kind];
}
