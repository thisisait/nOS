/**
 * The face app registry — one address space for every app the shell can name,
 * carrying the TWO independent axes (`docs/doctrine/face-app-tiers.md` §Form):
 *
 *   form  — what the app IS on screen: view | utility | widget | frame
 *   build — what it COSTS to build: F1–F4 / H
 *
 * WHAT THIS REPLACED. Until 2026-08-07 the shell recorded one binary,
 * `isNativeApp(slug)`: "a nos-native API-calling app rather than an iframe".
 * That answers exactly one question — component or iframe — and the estate
 * grew a third answer (a WIDGET: native, component-backed, and not a window)
 * that the binary could not express at all. `form` replaces it. `appForm()`
 * is the successor call; `isNativeApp` is gone, and the gate refuses its
 * return.
 *
 * A `frame` entry has NO component: a hub service is rendered by
 * `ServiceFrame` from the window's url. It also has no `build` — a service is
 * not an agent-built face app, and inventing an F-tier for it would make the
 * two axes look like one. Absence there is a stated fact, not a gap.
 *
 * The registry is a plain module singleton (pure logic, unit-testable in
 * node). Component loaders are LAZY dynamic imports so this module never
 * statically imports a `.svelte` file — that keeps it loadable in node/vitest.
 *
 * ── INTEGRATION (what `+page.svelte` wires) ───────────────────────────────
 *   1. On mount:     registerBuiltinNativeApps()
 *   2. Hub resolves: registerHubFrames(apps)      // form=frame, no component
 *   3. Dock/palette: appsOfForm('view', 'utility')  — a widget is not a dock
 *                    tile and a frame is launched from the hub catalog
 *   4. Window body:  resolveNativeComponent(win.app) via <NativeHost />
 *   5. Widgets:      <WidgetLayer /> resolves appsOfForm('widget') itself
 */
import type { Component } from 'svelte';
import { openWindow } from '$lib/stores/desktop';
import { APP_FORMS } from '$lib/contracts';
import type { AppBuild, AppForm, HubApp } from '$lib/contracts';

/** A lazily-loaded native component (the default export of a `.svelte` file). */
export type NativeComponentLoader = () => Promise<{ default: Component }>;

/** Descriptor for one face app. */
export interface FaceApp {
	/** Stable slug — also the `WindowModel.app` value a window carries. */
	slug: string;
	title: string;
	/** Emoji/text icon (rendered as escaped text, never HTML). */
	icon: string;
	/** What the app IS. Exactly one, always declared. */
	form: AppForm;
	/** What the app COSTS to build. Absent iff `form === 'frame'`. */
	build?: AppBuild;
	/** Lazy component loader. Required unless `form === 'frame'`. */
	component?: NativeComponentLoader;
	/** Default window size when launched (forms that open windows). */
	defaultSize?: { w: number; h: number };
	/** Declared BFF scopes this app calls (e.g. `['vfs', 'userstate']`). Metadata
	 *  for the Wave-2 wiring linter — not enforced at runtime here. */
	apiScopes?: string[];
	/** The user-state namespace this app owns (`app.<name>`; F1 recipe). */
	stateNamespace?: string;
}

const registry = new Map<string, FaceApp>();

/**
 * Register (or replace) a face app. Idempotent per slug — last write wins, so
 * re-running `registerBuiltinNativeApps()` on HMR is safe.
 *
 * Throws on the one incoherence the two axes make possible: a component-backed
 * form with no component, or a frame carrying one. That is a programming
 * error, not a runtime condition — every call site passes literals — and a
 * throw makes it a failing unit test instead of a window that renders nothing.
 */
export function registerNativeApp(app: FaceApp): void {
	if (app.form === 'frame' && app.component)
		throw new TypeError(`${app.slug}: form=frame carries a component — a frame is an iframe`);
	if (app.form !== 'frame' && !app.component)
		throw new TypeError(`${app.slug}: form=${app.form} needs a component loader`);
	registry.set(app.slug, app);
}

/**
 * Register the hub catalog as frames. Their form is not a declaration the
 * catalog makes — it is what the shell DOES with them (`ServiceFrame`) — so it
 * is asserted here, beside the render path, and nowhere else.
 *
 * A slug already registered by a component-backed app is left alone and
 * returned as a skip: a native app and a hub service can collide on a slug,
 * and the component-backed one is the one the shell renders.
 */
export function registerHubFrames(apps: readonly HubApp[]): {
	registered: number;
	skipped: string[];
} {
	const skipped: string[] = [];
	let registered = 0;
	for (const a of apps) {
		const existing = registry.get(a.slug);
		if (existing && existing.form !== 'frame') {
			skipped.push(a.slug);
			continue;
		}
		registerNativeApp({ slug: a.slug, title: a.title, icon: a.icon, form: 'frame' });
		registered++;
	}
	return { registered, skipped };
}

/** Every registered app, in insertion order — all four forms. */
export function faceApps(): FaceApp[] {
	return [...registry.values()];
}

/** Registered apps of the given form(s), in insertion order. */
export function appsOfForm(...forms: readonly AppForm[]): FaceApp[] {
	const want = new Set(forms);
	return faceApps().filter((a) => want.has(a.form));
}

/** Look up a descriptor by slug. */
export function getNativeApp(slug: string): FaceApp | undefined {
	return registry.get(slug);
}

/**
 * The form of a registered app, or `null` when the slug is not registered.
 *
 * NULL IS NOT `frame`. An unknown slug is an unknown slug — guessing `frame`
 * would let a typo render as a service, and would make the hub catalog's
 * arrival (which is asynchronous) indistinguishable from its failure.
 */
export function appForm(slug: string): AppForm | null {
	return registry.get(slug)?.form ?? null;
}

/** How many apps of each form are registered right now. Frames land only once
 *  the hub catalog resolves, so a `frame: 0` here means "not loaded (or the
 *  catalog failed)", never "there are none" — the caller must say which. */
export function formCounts(): Record<AppForm, number> {
	// Seeded from the GENOME's vocabulary rather than from four names typed
	// here: a fifth form would otherwise be registered by the shell, stamped by
	// the anatomy compiler, and silently missing from this census.
	const out = Object.fromEntries(APP_FORMS.map((f) => [f, 0])) as Record<AppForm, number>;
	for (const a of registry.values()) out[a.form]++;
	return out;
}

/**
 * Open a window for an app. Returns the new window id, or `null` if the slug
 * is not registered (caller can fall back to catalog launch) — or if its form
 * does not open a window. A WIDGET IS NOT A WINDOW: it is mounted by the
 * widget layer, and launching one would give the operator an empty frame
 * around a surface that is already on screen.
 */
export function launchNative(slug: string): string | null {
	const app = registry.get(slug);
	if (!app || app.form === 'widget' || app.form === 'frame') return null;
	return openWindow({
		app: app.slug,
		title: app.title,
		w: app.defaultSize?.w ?? 720,
		h: app.defaultSize?.h ?? 480
	});
}

/**
 * The component seam. Given a slug, returns a `Promise<Component>` for the
 * app's component, or `null` when the slug is unregistered or is a frame (the
 * shell then renders its iframe/placeholder body).
 */
export function resolveNativeComponent(slug: string): Promise<Component> | null {
	const loader = registry.get(slug)?.component;
	return loader ? loader().then((m) => m.default) : null;
}

/**
 * Register the built-in component-backed apps. The file-picker is a *service*,
 * not a dock app, so it is not registered here — mount it via
 * `initFilePickerBridge()` + the <FilePicker /> host instead.
 */
export function registerBuiltinNativeApps(): void {
	registerNativeApp({
		slug: 'files',
		title: 'Files',
		icon: '🗂',
		form: 'view',
		build: 'F1',
		component: () => import('./FilesApp.svelte'),
		defaultSize: { w: 760, h: 520 },
		apiScopes: ['vfs'],
		stateNamespace: 'app.files'
	});
	registerNativeApp({
		slug: 'tables',
		title: 'Tables',
		icon: '🧮',
		form: 'view',
		build: 'F2',
		component: () => import('./TablesApp.svelte'),
		defaultSize: { w: 920, h: 600 },
		apiScopes: ['tables'],
		stateNamespace: 'app.tables'
	});
	// Anatomy — Pulse / Wing / Bone as three views of ONE app. Tier-1 only;
	// the BFF re-enforces that, so a non-admin who launches it gets a 403 in
	// the view rather than a silently empty screen.
	registerNativeApp({
		slug: 'anatomy',
		title: 'Anatomy',
		icon: '🫀',
		form: 'view',
		build: 'F3',
		component: () => import('./anatomy/AnatomyApp.svelte'),
		defaultSize: { w: 980, h: 660 },
		apiScopes: ['pulse']
	});
	// Planner — the roadmap DataTable as an interactive Svelte Flow graph
	// (face-planner). Read-only first; the editor slices add write-back through
	// the tables BFF. Reads roadmap via /bff/tables, so it needs the tables scope.
	registerNativeApp({
		slug: 'planner',
		title: 'Planner',
		icon: '🗺',
		form: 'view',
		build: 'F3',
		component: () => import('./planner/PlannerApp.svelte'),
		defaultSize: { w: 1040, h: 700 },
		apiScopes: ['tables']
	});
	registerNativeApp({
		slug: 'keap-explore',
		title: 'Explore',
		icon: '🕸',
		form: 'view',
		build: 'F3',
		component: () => import('./KeapExploreApp.svelte'),
		defaultSize: { w: 1040, h: 700 },
		apiScopes: ['config']
	});
	// The first WIDGET. Small by contract — it is mounted by <WidgetLayer />
	// on the desktop, never opened as a window (launchNative refuses it).
	registerNativeApp({
		slug: 'anatomy-widget',
		title: 'Anatomy at a glance',
		icon: '🫀',
		form: 'widget',
		build: 'F1',
		component: () => import('../widgets/AnatomyWidget.svelte'),
		apiScopes: ['pulse']
	});
}

/** Test hook — clear the registry between unit tests. */
export function _resetRegistry(): void {
	registry.clear();
}
