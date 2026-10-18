// How Iris reaches the thalamus. The pupil hands it the Tauri bridge (pupil/src/transport.tauri.ts,
// the only file that names it); the face will hand it a web one. resume, workspace_load and
// workspace_save are wire messages, so they ride `send`; the layout calls are the local cache.
import type { Link, ToShell, ToThalamus } from './wire';
import type { Layout } from './workspace';

export interface Transport {
	connect(): Promise<void>;
	send(msg: ToThalamus): Promise<void>;
	// Resolves once listening: Iris connects only after both are, or the first `link` is missed.
	onShell(cb: (msg: ToShell) => void): Promise<() => void>;
	onLink(cb: (link: Link) => void): Promise<() => void>;
	loadLayout(): Promise<Layout>;
	saveLayout(layout: Layout): Promise<void>;
	// Where the file went, said back to the person.
	exportCsv(name: string, csv: string): Promise<string>;
}
