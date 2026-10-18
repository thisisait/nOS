// Iris's transport in the pupil: the Rust bridge (src-tauri/src/bridge.rs, workspace.rs, export.rs).
// The only file that names the Tauri bridge (test_pupil_webview_is_closed); window API comes from
// withGlobalTauri. null outside the app: Iris then says there is no bridge.
import type { Transport } from '$iris/transport';
import type { Link, ToShell } from '$iris/wire';
import type { Layout } from '$iris/workspace';

type Tauri = {
	core: { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> };
	event: { listen: <T>(ev: string, cb: (e: { payload: T }) => void) => Promise<() => void> };
};

export function tauriTransport(): Transport | null {
	const tauri = (globalThis as { __TAURI__?: Tauri }).__TAURI__;
	if (!tauri) return null;
	const { invoke } = tauri.core;
	const done = () => {};
	return {
		connect: () => invoke('connect').then(done),
		send: (msg) => invoke('send', { msg }).then(done),
		onShell: (cb) => tauri.event.listen<ToShell>('to_shell', ({ payload }) => cb(payload)),
		onLink: (cb) => tauri.event.listen<Link>('link', ({ payload }) => cb(payload)),
		loadLayout: () => invoke('load_layout') as Promise<Layout>,
		saveLayout: (layout) => invoke('save_layout', { layout }).then(done),
		exportCsv: (name, csv) => invoke('export_csv', { name, csv }) as Promise<string>
	};
}
