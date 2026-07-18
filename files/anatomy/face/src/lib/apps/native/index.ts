/**
 * nOS native-app framework — public surface for the shell integrator.
 *
 * WIRING (in the frozen `+page.svelte`, which G5 does not edit):
 *   import {
 *     registerBuiltinNativeApps, nativeApps, launchNative,
 *     isNativeApp, resolveNativeComponent
 *   } from '$lib/apps/native';
 *   import FilePicker from '$lib/apps/native/file-picker/FilePicker.svelte';
 *   import { initFilePickerBridge } from '$lib/apps/native/file-picker';
 *
 *   onMount(() => {
 *     registerBuiltinNativeApps();                 // registers the Files app
 *     const stop = initFilePickerBridge({ allowedOrigins: ['https://app.dev.local'] });
 *     return stop;                                 // dispose on teardown
 *   });
 *
 *   // Dock: render nativeApps() tiles alongside the hub catalog; click →
 *   //       launchNative(app.slug).
 *   // Window body: replace the placeholder with
 *   //   {#if isNativeApp(win.app)}
 *   //     {#await resolveNativeComponent(win.app) then Comp}
 *   //       {#if Comp}<Comp />{/if}
 *   //     {/await}
 *   //   {:else}…existing iframe/placeholder…{/if}
 *   // Mount <FilePicker /> once at desktop root (the picker host).
 */
export {
	registerNativeApp,
	registerBuiltinNativeApps,
	nativeApps,
	getNativeApp,
	isNativeApp,
	launchNative,
	resolveNativeComponent,
	_resetRegistry,
	type NativeApp,
	type NativeComponentLoader
} from './registry';

export { normalizePath, joinPath, parentPath, basename, crumbs, type Crumb } from './paths';

export { openFilePicker } from './file-picker/service';
export { initFilePickerBridge, MSG_OPEN, MSG_RESULT } from './file-picker/bridge';
export type { FilePickerOptions, PickResult } from './file-picker/types';
