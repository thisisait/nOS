import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { windows, _reset as _resetDesktop } from '$lib/stores/desktop';
import {
	registerNativeApp,
	nativeApps,
	getNativeApp,
	isNativeApp,
	launchNative,
	resolveNativeComponent,
	_resetRegistry,
	type NativeApp
} from './registry';
import { normalizePath, joinPath, parentPath, basename, crumbs } from './paths';

// A stub loader — never actually imported in these tests (registry is lazy).
const stub: NativeApp = {
	slug: 'files',
	title: 'Files',
	icon: '🗂',
	component: async () => ({ default: {} as never }),
	defaultSize: { w: 800, h: 600 },
	apiScopes: ['vfs'],
	stateNamespace: 'app.files'
};

beforeEach(() => {
	_resetRegistry();
	_resetDesktop();
});

describe('native-app registry', () => {
	it('registers and lists apps', () => {
		expect(nativeApps()).toHaveLength(0);
		registerNativeApp(stub);
		expect(nativeApps().map((a) => a.slug)).toEqual(['files']);
		expect(getNativeApp('files')?.title).toBe('Files');
		expect(isNativeApp('files')).toBe(true);
		expect(isNativeApp('grafana')).toBe(false);
	});

	it('last write wins per slug (HMR-safe idempotent register)', () => {
		registerNativeApp(stub);
		registerNativeApp({ ...stub, title: 'Files v2' });
		expect(nativeApps()).toHaveLength(1);
		expect(getNativeApp('files')?.title).toBe('Files v2');
	});

	it('launchNative opens a window with the app slug + default size', () => {
		registerNativeApp(stub);
		const id = launchNative('files');
		expect(id).not.toBeNull();
		const win = get(windows)[0];
		expect(win.app).toBe('files');
		expect(win.w).toBe(800);
		expect(win.h).toBe(600);
	});

	it('launchNative returns null for an unregistered slug (no window)', () => {
		expect(launchNative('nope')).toBeNull();
		expect(get(windows)).toHaveLength(0);
	});

	it('resolveNativeComponent returns a promise for native, null otherwise', async () => {
		registerNativeApp(stub);
		const p = resolveNativeComponent('files');
		expect(p).not.toBeNull();
		await expect(p).resolves.toBeDefined();
		expect(resolveNativeComponent('grafana')).toBeNull();
	});
});

describe('path helpers', () => {
	it('normalizes . / .. / empty segments', () => {
		expect(normalizePath('documents//a/./b')).toBe('documents/a/b');
		expect(normalizePath('a/b/../c')).toBe('a/c');
		expect(normalizePath('/leading/slash')).toBe('leading/slash');
		expect(normalizePath('a/../..')).toBe('');
		expect(normalizePath('')).toBe('');
	});

	it('joins base + child', () => {
		expect(joinPath('documents', 'file.txt')).toBe('documents/file.txt');
		expect(joinPath('', 'inbox')).toBe('inbox');
		expect(joinPath('a/b', '../c')).toBe('a/c');
	});

	it('parentPath and basename', () => {
		expect(parentPath('a/b/c')).toBe('a/b');
		expect(parentPath('a')).toBe('');
		expect(basename('a/b/c.txt')).toBe('c.txt');
		expect(basename('')).toBe('');
	});

	it('crumbs build a root-inclusive trail', () => {
		expect(crumbs('documents/reports')).toEqual([
			{ name: 'home', path: '' },
			{ name: 'documents', path: 'documents' },
			{ name: 'reports', path: 'documents/reports' }
		]);
		expect(crumbs('', 'root')).toEqual([{ name: 'root', path: '' }]);
	});
});
