import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$lib/api/userstate', () => ({
	usGet: vi.fn(),
	usSet: vi.fn(() => Promise.resolve())
}));

import { usGet, usSet } from '$lib/api/userstate';
import {
	isSafeGradient,
	isSafeVfsPath,
	safeBackground,
	wallpapersFromTable,
	setWallpaper,
	initWallpaper,
	activeWallpaper,
	FALLBACK_WALLPAPERS,
	DESKTOP_NS,
	WALLPAPER_KEY
} from './wallpaper';
import type { WallpaperSpec, DataTable } from '$lib/contracts';

const mockGet = vi.mocked(usGet);
const mockSet = vi.mocked(usSet);

beforeEach(() => {
	mockGet.mockReset();
	mockSet.mockReset();
	mockSet.mockResolvedValue(undefined);
	activeWallpaper.set(FALLBACK_WALLPAPERS[0]);
});

describe('isSafeGradient', () => {
	it('accepts plain gradient functions', () => {
		expect(isSafeGradient('linear-gradient(160deg, #2a2d34, #0e1013)')).toBe(true);
		expect(isSafeGradient('radial-gradient(1200px 800px at 30% 20%, #16203a, #0b0d12 60%)')).toBe(
			true
		);
		expect(isSafeGradient('repeating-linear-gradient(45deg, #111, #222 10px)')).toBe(true);
		expect(isSafeGradient('conic-gradient(from 0deg, #111, #222)')).toBe(true);
	});
	it('rejects injection attempts', () => {
		expect(isSafeGradient('red; background: url(http://evil)')).toBe(false);
		expect(isSafeGradient('linear-gradient(#111,#222)} body{display:none')).toBe(false);
		expect(isSafeGradient('linear-gradient(#111, url(javascript:alert(1)))')).toBe(false);
		expect(isSafeGradient('linear-gradient(#111)/* x */')).toBe(false);
		expect(isSafeGradient('#ff0000')).toBe(false);
		expect(isSafeGradient('expression(alert(1))')).toBe(false);
		expect(isSafeGradient(undefined)).toBe(false);
		expect(isSafeGradient('')).toBe(false);
	});
});

describe('isSafeVfsPath', () => {
	it('accepts a plain relative path', () => {
		expect(isSafeVfsPath('wallpapers/mine.jpg')).toBe(true);
	});
	it('rejects traversal / injection', () => {
		expect(isSafeVfsPath('../../etc/passwd')).toBe(false);
		expect(isSafeVfsPath('a"); background:url(x)')).toBe(false);
		expect(isSafeVfsPath(undefined)).toBe(false);
	});
});

describe('safeBackground', () => {
	it('returns the gradient for a valid gradient spec', () => {
		const spec = FALLBACK_WALLPAPERS[1];
		expect(safeBackground(spec)).toBe(spec.gradient);
	});
	it('returns a proxied url for a valid image spec', () => {
		const spec: WallpaperSpec = {
			slug: 'x',
			name: 'X',
			kind: 'image',
			vfsPath: 'wp/a.png',
			system: false
		};
		expect(safeBackground(spec)).toContain('/bff/vfs?op=download&path=');
		expect(safeBackground(spec)).toContain('url(');
	});
	it('returns null for an invalid gradient', () => {
		const spec: WallpaperSpec = {
			slug: 'bad',
			name: 'Bad',
			kind: 'gradient',
			gradient: 'x;y',
			system: false
		};
		expect(safeBackground(spec)).toBeNull();
	});
	it('returns null for a bad image path', () => {
		const spec: WallpaperSpec = {
			slug: 'bad',
			name: 'Bad',
			kind: 'image',
			vfsPath: '../secret',
			system: false
		};
		expect(safeBackground(spec)).toBeNull();
	});
});

describe('wallpapersFromTable', () => {
	it('falls back to the built-ins for an empty/null table', () => {
		expect(wallpapersFromTable(null)).toEqual(FALLBACK_WALLPAPERS);
		const empty: DataTable = {
			slug: 'face.wallpapers',
			title: 'W',
			columns: [],
			rows: [],
			source: 'fallback'
		};
		expect(wallpapersFromTable(empty)).toEqual(FALLBACK_WALLPAPERS);
	});
	it('projects valid rows and drops unsafe ones', () => {
		const table: DataTable = {
			slug: 'face.wallpapers',
			title: 'W',
			source: 'keap',
			columns: [],
			rows: [
				{
					id: '1',
					slug: 'ok',
					name: 'OK',
					kind: 'gradient',
					gradient: 'linear-gradient(#111,#222)',
					system: false
				},
				{
					id: '2',
					slug: 'evil',
					name: 'Evil',
					kind: 'gradient',
					gradient: 'x; background:url(y)',
					system: false
				}
			]
		};
		const out = wallpapersFromTable(table);
		expect(out).toHaveLength(1);
		expect(out[0].slug).toBe('ok');
	});
});

describe('setWallpaper', () => {
	it('sets + persists a valid wallpaper', async () => {
		const spec = FALLBACK_WALLPAPERS[2];
		await setWallpaper(spec);
		expect(get(activeWallpaper).slug).toBe(spec.slug);
		expect(mockSet).toHaveBeenCalledWith(DESKTOP_NS, WALLPAPER_KEY, spec);
	});
	it('refuses an invalid wallpaper', async () => {
		const bad: WallpaperSpec = {
			slug: 'bad',
			name: 'Bad',
			kind: 'gradient',
			gradient: '}evil',
			system: false
		};
		await setWallpaper(bad);
		expect(get(activeWallpaper).slug).not.toBe('bad');
		expect(mockSet).not.toHaveBeenCalled();
	});
});

describe('initWallpaper', () => {
	it('loads a valid saved selection', async () => {
		const saved = FALLBACK_WALLPAPERS[3];
		mockGet.mockResolvedValue(saved);
		const out = await initWallpaper();
		expect(out.slug).toBe(saved.slug);
		expect(get(activeWallpaper).slug).toBe(saved.slug);
	});
	it('keeps the default when nothing is saved', async () => {
		mockGet.mockResolvedValue(null);
		const out = await initWallpaper();
		expect(out.slug).toBe(FALLBACK_WALLPAPERS[0].slug);
	});
	it('ignores an unsafe saved selection', async () => {
		mockGet.mockResolvedValue({
			slug: 'evil',
			name: 'E',
			kind: 'gradient',
			gradient: '}x',
			system: false
		});
		await initWallpaper();
		expect(get(activeWallpaper).slug).not.toBe('evil');
	});
});
