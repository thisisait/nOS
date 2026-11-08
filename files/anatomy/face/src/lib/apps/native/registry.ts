/**
 * The face app registry — one address space for every app the shell can name,
 * carrying the TWO independent axes (`ssot/doctrine/face-app-tiers.md` §Form):
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
import { openWindow, focusApp } from '$lib/stores/desktop';
import { APP_FORMS } from '$lib/contracts';
import type { AppBuild, AppForm, HubApp } from '$lib/contracts';
import type { LimbDecl } from '$lib/limbs/types';
import { request } from '$lib/limbs/request';
import { requestAnatomy, type AnatomyView } from '$lib/anatomy/focus';
import { listTables, loadTable } from '$lib/api/tables';
import { vfsList, vfsMove } from '$lib/api/vfs';
import { basename, joinPath, parentPath } from './paths';
import { reachesTier, type Tier } from '$lib/security/tier';
import { scopeTier } from '$lib/security/bffTiers';

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
	/** Actions Iris may take in this app (`$lib/limbs`); writes sit behind a card. */
	limbs?: LimbDecl[];
	/** The least privileged tier that may open it (1 admin .. 4 guest; row face-app-min-tier).
	 *  Required for every component-backed app; a hub frame is 4 (the hub already filtered it by
	 *  tierOf). It must reach every BFF route its apiScopes call (bffTiers.ts). */
	minTier?: Tier;
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
	if (app.form !== 'frame' && ![1, 2, 3, 4].includes(app.minTier as number))
		throw new TypeError(`${app.slug}: form=${app.form} needs a minTier 1-4`);
	const need = scopeTier(app.apiScopes);
	if ((app.minTier ?? 4) > need)
		throw new TypeError(
			`${app.slug}: minTier ${app.minTier ?? 4} opens an app whose BFF routes need tier ${need}`
		);
	registry.set(app.slug, app);
}

/** The person looking at this face (edge-trusted groups from the layout); null until set. */
let viewer: readonly string[] | null = null;

/** Set once the page has the identity. Until then nothing is hidden: the BFF and Wing refuse
 *  anyway (layers 2 and 3), so this layer only spares a person a tile that would answer 403. */
export function setViewer(groups: readonly string[] | undefined): void {
	viewer = groups ?? [];
}

/** May the viewer open this app? */
export function mayOpen(app: FaceApp): boolean {
	return viewer === null || reachesTier(app.minTier ?? 4, viewer);
}

/** appsOfForm, less what the viewer's tier may not open (dock, palette, widget layer). */
export function openableApps(...forms: readonly AppForm[]): FaceApp[] {
	return appsOfForm(...forms).filter(mayOpen);
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
		// The hub already filtered by tierOf; its tier still hides the tile from a lower viewer.
		const t = Math.min(4, Math.max(1, Math.round(a.tier || 4))) as Tier;
		registerNativeApp({ slug: a.slug, title: a.title, icon: a.icon, form: 'frame', minTier: t });
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
	if (!app || app.form === 'widget' || app.form === 'frame' || !mayOpen(app)) return null;
	return openWindow({
		app: app.slug,
		title: app.title,
		w: app.defaultSize?.w ?? 720,
		h: app.defaultSize?.h ?? 480
	});
}

/** Singleton rule (as +page.svelte launchNativeApp): focus first, else open. */
export function openApp(slug: string): boolean {
	return focusApp(slug) || launchNative(slug) !== null;
}

function fail(reason: string): never {
	throw new Error(reason);
}

/** A path a limb may touch: relative to the person's root, never `..` (Bone re-checks realpath). */
function mine(p: unknown): string {
	const s = String(p);
	if (s.startsWith('/') || s.startsWith('\\') || s.split('/').includes('..'))
		fail(`${s} is outside your files`);
	return s
		.split('/')
		.filter((x) => x && x !== '.')
		.join('/');
}

/** An app limb's run: bring the window forward, then leave the app a request. */
function show(slug: string, action: string, params: Record<string, unknown>): true {
	if (!openApp(slug)) fail(`cannot open ${slug}`);
	request(slug, action, params);
	return true;
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
		minTier: 4,
		title: 'Files',
		icon: '🗂',
		form: 'view',
		build: 'F1',
		component: () => import('./FilesApp.svelte'),
		defaultSize: { w: 760, h: 520 },
		apiScopes: ['vfs'],
		stateNamespace: 'app.files',
		limbs: [
			{
				action: 'reveal',
				params: { path: { type: 'string', required: true } },
				writes: false,
				says: 'Show a file or folder in Files (path from the home root)',
				run: async ({ path }) => {
					const name = basename(path as string);
					const there = await vfsList(parentPath(path as string));
					if (!name || !there.some((e) => e.name === name)) fail(`no such file ${path}`);
					return show('files', 'reveal', { path });
				}
			},
			{
				action: 'move',
				params: {
					path: { type: 'string', required: true },
					to: { type: 'string', required: true }
				},
				writes: true,
				says: 'Move a file or folder into another folder; never overwrites',
				run: async (p) => {
					const [path, to] = [mine(p.path), mine(p.to)];
					const name = basename(path);
					const here = await vfsList(parentPath(path));
					if (!name || !here.some((e) => e.name === name)) fail(`no such file ${path}`);
					if (to === path || to.startsWith(`${path}/`)) fail(`cannot move ${path} into itself`);
					const there = await vfsList(to).catch(() => fail(`no such folder ${to}`));
					const dst = joinPath(to, name);
					if (there.some((e) => e.name === name)) fail(`${dst} already exists`);
					await vfsMove(path, dst);
					return show('files', 'reveal', { path: dst });
				}
			}
		]
	});
	registerNativeApp({
		slug: 'tables',
		minTier: 4,
		title: 'Tables',
		icon: '🧮',
		form: 'view',
		build: 'F2',
		component: () => import('./TablesApp.svelte'),
		defaultSize: { w: 920, h: 600 },
		apiScopes: ['tables'],
		stateNamespace: 'app.tables',
		limbs: [
			{
				action: 'open_table',
				params: { slug: { type: 'string', required: true } },
				writes: false,
				says: 'Open a DataTable by its slug in Tables',
				run: async ({ slug }) => {
					if (!(await listTables()).some((t) => t.slug === slug)) fail(`no table ${slug}`);
					return show('tables', 'open_table', { slug });
				}
			}
		]
	});
	// Anatomy — Pulse / Wing / Bone as three views of ONE app. Tier-1 only;
	// the BFF re-enforces that, so a non-admin who launches it gets a 403 in
	// the view rather than a silently empty screen.
	registerNativeApp({
		slug: 'anatomy',
		minTier: 1,
		title: 'Anatomy',
		icon: '🫀',
		form: 'view',
		build: 'F3',
		component: () => import('./anatomy/AnatomyApp.svelte'),
		defaultSize: { w: 980, h: 660 },
		apiScopes: ['pulse'],
		limbs: [
			{
				action: 'show',
				params: {
					view: {
						type: 'enum',
						values: ['pulse', 'wing', 'bone', 'graph', 'runs'],
						required: true
					},
					thread: { type: 'string' },
					node: { type: 'string' }
				},
				writes: false,
				says: 'Show an Anatomy view; thread narrows Wing, node selects in Graph',
				// The Anatomy app already consumes anatomyFocus; no request() needed.
				run: ({ view, thread, node }) => {
					if (!openApp('anatomy')) fail('cannot open anatomy');
					requestAnatomy(view as AnatomyView, thread as string, node as string);
					return true;
				}
			}
		]
	});
	// Planner — the roadmap DataTable as an interactive Svelte Flow graph
	// (face-planner). Read-only first; the editor slices add write-back through
	// the tables BFF. Reads roadmap via /bff/tables, so it needs the tables scope.
	registerNativeApp({
		slug: 'planner',
		minTier: 2, // operator 2026-11-08: planning is manager+
		title: 'Planner',
		icon: '🗺',
		form: 'view',
		build: 'F3',
		component: () => import('./planner/PlannerApp.svelte'),
		defaultSize: { w: 1040, h: 700 },
		apiScopes: ['tables'],
		limbs: [
			{
				action: 'focus_row',
				params: { slug: { type: 'string', required: true } },
				writes: false,
				says: 'Open a roadmap row in the Planner graph by its slug',
				run: async ({ slug }) => {
					const t = await loadTable('roadmap');
					if (!t.rows.some((r) => r.slug === slug)) fail(`no roadmap row ${slug}`);
					return show('planner', 'focus_row', { slug });
				}
			}
		]
	});
	// Wing's inbox as a face app (row wing-inc1-inbox-app): the first Wing page moved to the face.
	registerNativeApp({
		slug: 'inbox',
		minTier: 1,
		title: 'Inbox',
		icon: '📥',
		form: 'view',
		build: 'F2',
		component: () => import('./InboxApp.svelte'),
		defaultSize: { w: 760, h: 620 },
		apiScopes: ['inbox']
	});
	// Wing's agents page as a face app (row wing-inc2-agents-timeline).
	registerNativeApp({
		slug: 'agents',
		minTier: 1,
		title: 'Agents',
		icon: '🤖',
		form: 'view',
		build: 'F2',
		component: () => import('./AgentsApp.svelte'),
		defaultSize: { w: 900, h: 600 },
		apiScopes: ['agents']
	});
	registerNativeApp({
		slug: 'keap-explore',
		minTier: 4,
		title: 'Explore',
		icon: '🕸',
		form: 'view',
		build: 'F3',
		component: () => import('./KeapExploreApp.svelte'),
		defaultSize: { w: 1040, h: 700 },
		apiScopes: ['config']
	});
	registerNativeApp({
		slug: 'books',
		minTier: 2, // operator 2026-11-08: the books are manager+
		title: 'Books',
		icon: '📒',
		form: 'view',
		build: 'F2',
		component: () => import('./BooksApp.svelte'),
		defaultSize: { w: 960, h: 640 },
		apiScopes: ['tables'],
		stateNamespace: 'app.books',
		limbs: [
			{
				action: 'show',
				params: {
					tab: {
						type: 'enum',
						values: ['queue', 'invoices', 'journals', 'parties'],
						required: true
					},
					slug: { type: 'string' }
				},
				writes: false,
				says: 'Show a Books tab; slug opens that queue row for review',
				run: (params) => show('books', 'show', params)
			}
		]
	});
	// Iris: the conversation onto the thalamus, the pupil's components on the BFF's optic
	// nerve (bff/iris). The layout is cached in app.iris; the thalamus holds the person's copy.
	registerNativeApp({
		slug: 'iris',
		minTier: 4,
		title: 'Iris',
		icon: '👁',
		form: 'view',
		build: 'F3',
		component: () => import('./IrisApp.svelte'),
		defaultSize: { w: 1100, h: 720 },
		apiScopes: ['iris'],
		stateNamespace: 'app.iris'
	});
	// The first WIDGET. Small by contract — it is mounted by <WidgetLayer />
	// on the desktop, never opened as a window (launchNative refuses it).
	registerNativeApp({
		slug: 'anatomy-widget',
		minTier: 1,
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
	viewer = null;
}
