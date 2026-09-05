import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { windows, _reset as _resetDesktop } from '$lib/stores/desktop';
import {
	registerNativeApp,
	registerBuiltinNativeApps,
	registerHubFrames,
	faceApps,
	appsOfForm,
	appForm,
	formCounts,
	getNativeApp,
	launchNative,
	resolveNativeComponent,
	_resetRegistry,
	type FaceApp
} from './registry';
import { normalizePath, joinPath, parentPath, basename, crumbs } from './paths';

// A stub loader — never actually imported in these tests (registry is lazy).
const stub: FaceApp = {
	slug: 'files',
	title: 'Files',
	icon: '🗂',
	form: 'view',
	build: 'F1',
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
		expect(faceApps()).toHaveLength(0);
		registerNativeApp(stub);
		expect(faceApps().map((a) => a.slug)).toEqual(['files']);
		expect(getNativeApp('files')?.title).toBe('Files');
		// `appForm` is the successor to the deleted `isNativeApp` binary. It
		// answers with the FORM, and NULL for an unregistered slug — not
		// `frame`, which would guess a typo into a service.
		expect(appForm('files')).toBe('view');
		expect(appForm('grafana')).toBeNull();
	});

	it('last write wins per slug (HMR-safe idempotent register)', () => {
		registerNativeApp(stub);
		registerNativeApp({ ...stub, title: 'Files v2' });
		expect(faceApps()).toHaveLength(1);
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

// ── the two axes (docs/doctrine/face-app-tiers.md §Form) ────────────────────

describe('form + build are two independent axes', () => {
	it('every built-in declares exactly one form and a build', () => {
		registerBuiltinNativeApps();
		for (const a of faceApps()) {
			expect(['view', 'utility', 'widget', 'frame']).toContain(a.form);
			expect(a.build).toBeDefined();
			expect(['F1', 'F2', 'F3', 'F4', 'H']).toContain(a.build);
		}
	});

	it('the population is 5 views and 1 widget until the hub arrives', () => {
		registerBuiltinNativeApps();
		// 5 views: files, tables, anatomy, planner (face-planner), keap-explore.
		expect(formCounts()).toEqual({ view: 5, utility: 0, widget: 1, frame: 0 });
	});

	it('neither axis determines the other', () => {
		registerBuiltinNativeApps();
		// Same form, different builds: `view` spans F1..F3. If `build` could be
		// read off `form` this set would have one element, and the two fields
		// would be one field with two names.
		const viewBuilds = new Set(appsOfForm('view').map((a) => a.build));
		expect(viewBuilds.size).toBeGreaterThan(1);
		// Same build, different forms: F1 is both a view (Files) and a widget.
		const f1Forms = new Set(
			faceApps()
				.filter((a) => a.build === 'F1')
				.map((a) => a.form)
		);
		expect(f1Forms.size).toBeGreaterThan(1);
	});

	it('a frame carries no component and no build; a non-frame must carry one', () => {
		registerHubFrames([
			{ slug: 'grafana', title: 'Grafana', icon: '📊', url: '/g', description: '', tier: 1 }
		]);
		expect(appForm('grafana')).toBe('frame');
		expect(getNativeApp('grafana')?.component).toBeUndefined();
		expect(getNativeApp('grafana')?.build).toBeUndefined();
		expect(() => registerNativeApp({ slug: 'x', title: 'x', icon: 'x', form: 'view' })).toThrow(
			/needs a component/
		);
		expect(() =>
			registerNativeApp({
				slug: 'y',
				title: 'y',
				icon: 'y',
				form: 'frame',
				component: async () => ({ default: {} as never })
			})
		).toThrow(/frame is an iframe/);
	});

	it('a hub frame never displaces a component-backed app of the same slug', () => {
		registerNativeApp(stub);
		const { registered, skipped } = registerHubFrames([
			{ slug: 'files', title: 'Files (service)', icon: '📁', url: '/f', description: '', tier: 3 }
		]);
		expect(registered).toBe(0);
		expect(skipped).toEqual(['files']);
		expect(appForm('files')).toBe('view');
	});

	it('a widget is not a window — launchNative refuses it', () => {
		registerNativeApp({
			slug: 'w',
			title: 'W',
			icon: 'W',
			form: 'widget',
			build: 'F1',
			component: async () => ({ default: {} as never })
		});
		expect(launchNative('w')).toBeNull();
		expect(get(windows)).toHaveLength(0);
		// …but it IS a registered app with a resolvable component: the widget
		// layer mounts it through the same seam a window body uses.
		expect(appsOfForm('widget').map((a) => a.slug)).toEqual(['w']);
		expect(resolveNativeComponent('w')).not.toBeNull();
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
