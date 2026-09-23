import { describe, it, expect } from 'vitest';
import { BREAKPOINTS, MEDIA, resolveMode, usesWindows, frontWindow, type LayoutMode } from './mode';
import type { WindowModel } from '$lib/contracts';

const at = (width: number, coarsePointer = false): LayoutMode =>
	resolveMode({ width, coarsePointer });

describe('layout mode', () => {
	it('resolves the three width bands', () => {
		expect(at(390)).toBe('mobile'); // iPhone portrait
		expect(at(719)).toBe('mobile');
		expect(at(720)).toBe('tablet'); // the boundary belongs to the band above
		expect(at(1024)).toBe('tablet');
		expect(at(1080)).toBe('desktop');
		expect(at(1920)).toBe('desktop');
	});

	it('a coarse pointer never reaches desktop — but never forces mobile either', () => {
		expect(at(1920, true)).toBe('tablet');
		expect(at(390, true)).toBe('mobile');
		expect(at(390, false)).toBe('mobile'); // a narrow mouse window is still mobile
	});

	it('only mobile drops the window manager', () => {
		expect(usesWindows('mobile')).toBe(false);
		expect(usesWindows('tablet')).toBe(true);
		expect(usesWindows('desktop')).toBe(true);
	});

	it('the media queries derive from the breakpoints — no second declaration', () => {
		expect(MEDIA.mobile).toBe(`(max-width: ${BREAKPOINTS.mobile - 0.02}px)`);
		expect(MEDIA.tablet).toBe(`(max-width: ${BREAKPOINTS.tablet - 0.02}px)`);
		// The query and the rule must agree at the boundary.
		expect(at(BREAKPOINTS.mobile - 1)).toBe('mobile');
		expect(at(BREAKPOINTS.mobile)).not.toBe('mobile');
	});
});

const win = (id: string, z: number, min = false) =>
	({ id, app: id, title: id, x: 0, y: 0, w: 1, h: 1, z, min, max: false }) as WindowModel;

describe('mobile app stacking', () => {
	it('shows the front-most window', () => {
		expect(frontWindow([win('a', 3), win('b', 9), win('c', 5)])?.id).toBe('b');
	});

	it('skips minimised windows — they are not on screen', () => {
		expect(frontWindow([win('a', 3), win('b', 9, true)])?.id).toBe('a');
	});

	it('nothing open (or everything minimised) means the home screen', () => {
		expect(frontWindow([])).toBeNull();
		expect(frontWindow([win('a', 3, true)])).toBeNull();
	});
});
