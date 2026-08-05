/**
 * Grapheme-safe glyph handling for app icons.
 *
 * WHY THIS EXISTS — a measured bug, not a tidiness argument. `Dock.svelte`
 * rendered `app.icon.slice(0, 2)`, and `.slice()` counts UTF-16 code units, not
 * characters. Verified in node on 2026-08-05:
 *
 *     "🫀".slice(0,2)      → "🫀"        fine (one surrogate pair)
 *     "⚡🔥".slice(0,2)     → "⚡\ud83d"   A LONE SURROGATE → renders "⚡�"
 *     "🇨🇿".slice(0,2)     → "🇨"        half a flag → renders a letter box
 *     "👨‍👩‍👧".slice(0,2)  → "👨"        acceptable, but by luck
 *
 * The two-emoji case is reachable: hub icons come from an operator-authored
 * `hub_card` glyph that the BFF passes through untouched, so an operator typing
 * two emoji gets a replacement character and no explanation.
 *
 * `Intl.Segmenter` is the correct tool — it splits on grapheme clusters, so a
 * ZWJ family, a flag and a variation-selector sequence each count as one. It
 * has been in every browser baseline since 2024; the fallback below is for
 * older engines and for `vitest` running on a node without full ICU.
 *
 * Pure module — vitest runs it in node.
 */

/** Split a string into grapheme clusters (user-perceived characters). */
export function graphemes(s: string): string[] {
	if (typeof Intl !== 'undefined' && 'Segmenter' in Intl) {
		const seg = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
		return [...seg.segment(s)].map((g) => g.segment);
	}
	// Fallback: code POINTS, not code units. Still wrong for ZWJ sequences —
	// it splits a family into people — but it never produces a lone surrogate,
	// which is the failure that renders as mojibake rather than as a different
	// picture.
	return [...s];
}

/**
 * At most `max` whole glyphs. Never cuts inside a grapheme.
 *
 * Returns '' for empty input rather than a placeholder — the caller decides
 * what an absent icon looks like, and `monogram()` below is the usual answer.
 */
export function clampGlyphs(icon: string, max = 2): string {
	const trimmed = (icon ?? '').trim();
	if (!trimmed) return '';
	return graphemes(trimmed).slice(0, max).join('');
}

/**
 * Fallback icon for an app with none: the first letter of its title.
 *
 * A letter is legible, unique-ish and needs no font. The alternative — a
 * generic box glyph — makes every icon-less app look like the same app.
 */
export function monogram(title: string): string {
	const first = graphemes((title ?? '').trim())[0] ?? '';
	return first.toUpperCase() || '•';
}

/** The glyph to render for an app: its icon, clamped, else a monogram. */
export function appGlyph(icon: string | undefined, title: string, max = 2): string {
	return clampGlyphs(icon ?? '', max) || monogram(title);
}
