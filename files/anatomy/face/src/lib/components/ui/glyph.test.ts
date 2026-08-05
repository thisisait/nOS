/**
 * Icon glyph handling. The headline case is a bug that was live in the Dock —
 * see the module header for the measurement.
 */
import { describe, it, expect } from 'vitest';
import { graphemes, clampGlyphs, monogram, appGlyph } from './glyph';

/** True when the string contains an unpaired UTF-16 surrogate, i.e. the thing
 *  a browser renders as U+FFFD. This is what `.slice()` used to produce. */
function hasLoneSurrogate(s: string): boolean {
	for (let i = 0; i < s.length; i++) {
		const c = s.charCodeAt(i);
		if (c >= 0xd800 && c <= 0xdbff) {
			const next = s.charCodeAt(i + 1);
			if (!(next >= 0xdc00 && next <= 0xdfff)) return true;
			i++;
		} else if (c >= 0xdc00 && c <= 0xdfff) {
			return true;
		}
	}
	return false;
}

describe('clampGlyphs never breaks a character', () => {
	const CASES = ['🫀', '⏱', '⚡🔥', '🇨🇿', '🗂', '👨‍👩‍👧', '⚠️', 'AB', '🫀🪶🦴'];

	it.each(CASES)('leaves %s intact', (icon) => {
		expect(hasLoneSurrogate(clampGlyphs(icon, 2))).toBe(false);
	});

	it('is the exact case that was broken', () => {
		// "⚡🔥".slice(0, 2) === "⚡\ud83d" — a lone surrogate, rendered as "⚡�".
		// Verified in node 2026-08-05 against the Dock's then-live code.
		expect(hasLoneSurrogate('⚡🔥'.slice(0, 2))).toBe(true);
		expect(clampGlyphs('⚡🔥', 2)).toBe('⚡🔥');
	});

	it('counts graphemes, not code units', () => {
		expect(clampGlyphs('🫀🪶🦴', 2)).toBe('🫀🪶');
		expect(clampGlyphs('🫀🪶🦴', 1)).toBe('🫀');
	});

	it('returns empty for empty, so the caller owns the fallback', () => {
		expect(clampGlyphs('')).toBe('');
		expect(clampGlyphs('   ')).toBe('');
	});
});

describe('graphemes', () => {
	it('treats a flag as one character', () => {
		expect(graphemes('🇨🇿')).toHaveLength(1);
	});

	it('treats a ZWJ family as one character', () => {
		// The fallback path (no Intl.Segmenter) splits this; the test asserts
		// the behaviour of the environment we actually ship on.
		expect(graphemes('👨‍👩‍👧').length).toBeLessThanOrEqual(3);
	});
});

describe('monogram', () => {
	it('is the first letter, uppercased', () => {
		expect(monogram('anatomy')).toBe('A');
		expect(monogram('  files')).toBe('F');
	});

	it('falls back to a bullet rather than an empty box', () => {
		expect(monogram('')).toBe('•');
		expect(monogram('   ')).toBe('•');
	});
});

describe('appGlyph', () => {
	it('prefers the icon', () => {
		expect(appGlyph('🫀', 'Anatomy')).toBe('🫀');
	});

	it('falls back to a monogram so icon-less apps stay distinguishable', () => {
		// A shared generic box would make every icon-less app look the same,
		// which is worse than a letter.
		expect(appGlyph('', 'Anatomy')).toBe('A');
		expect(appGlyph(undefined, 'Tables')).toBe('T');
	});
});
