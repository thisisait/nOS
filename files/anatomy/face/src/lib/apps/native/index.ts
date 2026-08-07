/**
 * nOS face-app framework — public surface for the shell integrator.
 *
 * WIRING (in `+page.svelte`):
 *   import {
 *     registerBuiltinNativeApps, registerHubFrames, appsOfForm, launchNative,
 *     appForm, resolveNativeComponent
 *   } from '$lib/apps/native';
 *   import FilePicker from '$lib/apps/native/file-picker/FilePicker.svelte';
 *   import { initFilePickerBridge } from '$lib/apps/native/file-picker';
 *
 *   onMount(() => {
 *     registerBuiltinNativeApps();                 // the component-backed apps
 *     const stop = initFilePickerBridge({ allowedOrigins: ['https://app.dev.local'] });
 *     return stop;                                 // dispose on teardown
 *   });
 *
 *   // Dock: appsOfForm('view', 'utility') tiles alongside the hub catalog;
 *   //       click → launchNative(app.slug). Widgets are NOT dock tiles.
 *   // Window body: <NativeHost app={win.app} /> when the app has a component.
 *   // Widgets: <WidgetLayer /> once at desktop root.
 *   // Mount <FilePicker /> once at desktop root (the picker host).
 *
 * `isNativeApp` was deleted on 2026-08-07 — see `registry.ts`'s header. Use
 * `appForm(slug)`, which distinguishes the four forms the binary collapsed.
 */
export {
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
	type FaceApp,
	type NativeComponentLoader
} from './registry';

export { normalizePath, joinPath, parentPath, basename, crumbs, type Crumb } from './paths';

export { openFilePicker } from './file-picker/service';
export { initFilePickerBridge, MSG_OPEN, MSG_RESULT } from './file-picker/bridge';
export type { FilePickerOptions, PickResult } from './file-picker/types';
