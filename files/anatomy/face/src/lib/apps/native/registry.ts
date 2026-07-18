/**
 * Native-app registry (Tier F1, `docs/doctrine/face-app-tiers.md`).
 *
 * A "native" app is a Svelte component that CALLS the nOS BFF APIs directly —
 * it is NOT an iframe. Each app declares a small descriptor; the shell opens a
 * window whose body renders the app's component (see `resolveNativeComponent`
 * below for the integrator seam).
 *
 * The registry is a plain module singleton (pure logic, unit-testable in node).
 * Component loaders are LAZY dynamic imports so this module never statically
 * imports a `.svelte` file — that keeps it loadable in the node/vitest env.
 *
 * ── INTEGRATION (what `+page.svelte` wires; the store/page are frozen seams) ──
 *   1. On mount:  registerBuiltinNativeApps()   // + any bespoke registerNativeApp(...)
 *   2. Dock/launch:  launchNative(slug)          // openWindow(...) for the app
 *   3. Window body:  map win.app → the component. The frozen page renders a
 *      placeholder today; the integrator replaces that body with, e.g.:
 *
 *        {#if resolveNativeComponent(win.app)}
 *          {#await resolveNativeComponent(win.app) then Comp}
 *            {#if Comp}<Comp />{/if}
 *          {/await}
 *        {:else}
 *          <placeholder … />
 *        {/if}
 *
 *   `resolveNativeComponent(app)` returns a `Promise<Component>` for a native
 *   app, or `null` for a non-native (iframe/catalog) app so the shell falls
 *   back to its existing rendering.
 */
import type { Component } from 'svelte';
import { openWindow } from '$lib/stores/desktop';

/** A lazily-loaded native component (the default export of a `.svelte` file). */
export type NativeComponentLoader = () => Promise<{ default: Component }>;

/** Descriptor for one native (API-calling, non-iframe) app. */
export interface NativeApp {
	/** Stable slug — also the `WindowModel.app` value the window carries. */
	slug: string;
	title: string;
	/** Emoji/text icon (rendered as escaped text, never HTML). */
	icon: string;
	/** Lazy component loader (`() => import('./FooApp.svelte')`). */
	component: NativeComponentLoader;
	/** Default window size when launched. */
	defaultSize?: { w: number; h: number };
	/** Declared BFF scopes this app calls (e.g. `['vfs', 'userstate']`). Metadata
	 *  for the Wave-2 wiring linter — not enforced at runtime here. */
	apiScopes?: string[];
	/** The user-state namespace this app owns (`app.<name>`; F1 recipe). */
	stateNamespace?: string;
}

const registry = new Map<string, NativeApp>();

/** Register (or replace) a native app. Idempotent per slug — last write wins,
 *  so re-running `registerBuiltinNativeApps()` on HMR is safe. */
export function registerNativeApp(app: NativeApp): void {
	registry.set(app.slug, app);
}

/** All registered native apps, in insertion order. */
export function nativeApps(): NativeApp[] {
	return [...registry.values()];
}

/** Look up a descriptor by slug. */
export function getNativeApp(slug: string): NativeApp | undefined {
	return registry.get(slug);
}

/** True when `slug` names a registered native app (vs. an iframe/catalog app). */
export function isNativeApp(slug: string): boolean {
	return registry.has(slug);
}

/** Open a window for a native app. Returns the new window id, or `null` if the
 *  slug is not registered (caller can fall back to catalog/iframe launch). */
export function launchNative(slug: string): string | null {
	const app = registry.get(slug);
	if (!app) return null;
	return openWindow({
		app: app.slug,
		title: app.title,
		w: app.defaultSize?.w ?? 720,
		h: app.defaultSize?.h ?? 480
	});
}

/**
 * The window-body integrator seam. Given a window's `app` slug, returns a
 * `Promise<Component>` for the native component to render, or `null` when the
 * slug is not a native app (the shell then renders its iframe/placeholder body).
 */
export function resolveNativeComponent(slug: string): Promise<Component> | null {
	const loader = registry.get(slug)?.component;
	return loader ? loader().then((m) => m.default) : null;
}

/**
 * Register the built-in native apps (currently the reference Files app). The
 * file-picker is a *service*, not a dock app, so it is not registered here —
 * mount it via `initFilePickerBridge()` + the <FilePicker /> host instead.
 */
export function registerBuiltinNativeApps(): void {
	registerNativeApp({
		slug: 'files',
		title: 'Files',
		icon: '🗂',
		component: () => import('./FilesApp.svelte'),
		defaultSize: { w: 760, h: 520 },
		apiScopes: ['vfs'],
		stateNamespace: 'app.files'
	});
}

/** Test hook — clear the registry between unit tests. */
export function _resetRegistry(): void {
	registry.clear();
}
