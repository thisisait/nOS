/**
 * The severity vocabulary's job is to keep four states from collapsing into
 * each other. These tests pin exactly that, and nothing about how it looks.
 */
import { describe, it, expect } from 'vitest';
import {
	STATUS_KINDS,
	STATUS_TONE,
	STATUS_GLYPH,
	TONES,
	toneVars,
	exitTone,
	severityTone
} from './tone';

describe('the status kinds stay distinguishable', () => {
	it('gives every kind a tone and a glyph', () => {
		for (const k of STATUS_KINDS) {
			expect(STATUS_TONE[k], `no tone for ${k}`).toBeDefined();
			expect(STATUS_GLYPH[k], `no glyph for ${k}`).toBeTruthy();
		}
	});

	it('renders every kind differently from every other', () => {
		// The whole point. If two kinds share both tone and glyph they are
		// visually one state, and a caller distinguishing them in code is
		// distinguishing nothing on screen.
		const seen = new Map<string, string>();
		for (const k of STATUS_KINDS) {
			const sig = `${STATUS_TONE[k]}|${STATUS_GLYPH[k]}`;
			expect(seen.has(sig), `${k} is indistinguishable from ${seen.get(sig)}`).toBe(false);
			seen.set(sig, k);
		}
	});

	it('never colours an empty result as ok', () => {
		// "There is nothing here" is the absence of news, not good news. A
		// green empty state is how a blank panel starts reading as a healthy
		// one — the defect this whole vocabulary exists to prevent.
		expect(STATUS_TONE.empty).not.toBe('ok');
		expect(STATUS_TONE.loading).not.toBe('ok');
	});

	it('makes `unwired` visible rather than quiet', () => {
		// Nothing is broken, but nothing is being watched either.
		expect(STATUS_TONE.unwired).toBe('warn');
	});
});

describe('tone variables', () => {
	it('resolves every tone to three distinct custom properties', () => {
		for (const t of TONES) {
			const v = toneVars(t);
			expect(v.ink).toBeTruthy();
			expect(v.soft).toBeTruthy();
			expect(v.solid).toBeTruthy();
		}
	});

	it('points non-neutral tones at the app.css tokens', () => {
		expect(toneVars('bad').solid).toBe('var(--bad)');
		expect(toneVars('warn').ink).toBe('var(--warn-ink)');
	});
});

describe('exitTone', () => {
	it('is ok only for a reported zero', () => {
		expect(exitTone(0)).toBe('ok');
		expect(exitTone(1)).toBe('bad');
		expect(exitTone(255)).toBe('bad');
	});

	it('treats "no result yet" as in-flight, never as success', () => {
		// A run with a NULL exit code has not reported. Calling that ok would
		// be a success marker written by something other than a reader.
		expect(exitTone(null)).toBe('info');
		expect(exitTone(undefined)).toBe('info');
	});
});

describe('severityTone', () => {
	it('maps the A9 severities', () => {
		expect(severityTone('critical')).toBe('bad');
		expect(severityTone('HIGH')).toBe('bad');
		expect(severityTone('medium')).toBe('warn');
		expect(severityTone('low')).toBe('info');
	});

	it('leaves an unknown severity neutral rather than guessing', () => {
		expect(severityTone('spicy')).toBe('neutral');
		expect(severityTone(null)).toBe('neutral');
		expect(severityTone(undefined)).toBe('neutral');
	});
});
