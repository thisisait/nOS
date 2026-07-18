/**
 * postMessage bridge for the file-picker service.
 *
 * Lets an iframe-embedded (non-face-native) app request a pick from the shell:
 * it posts `{ type: 'nos:file-picker:open', requestId, opts }` to the shell
 * window; the shell opens its picker and posts back
 * `{ type: 'nos:file-picker:result', requestId, result }` to the requester.
 *
 * The integrator mounts this once (alongside the <FilePicker /> host):
 *
 *     const stop = initFilePickerBridge({ allowedOrigins: ['https://app.dev.local'] });
 *     // …later: stop();   // remove the listener
 *
 * ⚠️ SECURITY — origin check is the trust boundary. Pass `allowedOrigins` to
 * restrict which embedded apps may drive the picker. See the TODO below before
 * shipping to production (Wave-2 gate): with no allowlist this currently honors
 * ANY origin, which is only acceptable in dev.
 */
import { openFilePicker } from './service';
import type { FilePickerOptions } from './types';

export const MSG_OPEN = 'nos:file-picker:open';
export const MSG_RESULT = 'nos:file-picker:result';

interface OpenMessage {
	type: typeof MSG_OPEN;
	requestId?: string;
	opts?: FilePickerOptions;
}

export interface FilePickerBridgeOptions {
	/** Exact origins allowed to drive the picker. When omitted, ALL origins are
	 *  accepted — dev only; MUST be set in production. */
	allowedOrigins?: string[];
}

function isOpenMessage(data: unknown): data is OpenMessage {
	return (
		typeof data === 'object' && data !== null && (data as { type?: unknown }).type === MSG_OPEN
	);
}

/** Mount the bridge listener. Returns a disposer that removes it. */
export function initFilePickerBridge(opts: FilePickerBridgeOptions = {}): () => void {
	const handler = async (ev: MessageEvent) => {
		if (!isOpenMessage(ev.data)) return;

		// TODO(security, Wave-2 gate): enforce the origin allowlist unconditionally.
		// A sandboxed iframe reports origin "null"; decide per-deployment whether to
		// trust it. Until an allowlist is configured we accept any origin (DEV ONLY).
		if (opts.allowedOrigins && !opts.allowedOrigins.includes(ev.origin)) return;

		const requestId = ev.data.requestId;
		const result = await openFilePicker(ev.data.opts ?? {});

		const source = ev.source as Window | null;
		// Reply to the exact requesting origin; "null" (sandboxed) → wildcard.
		const target = ev.origin && ev.origin !== 'null' ? ev.origin : '*';
		source?.postMessage({ type: MSG_RESULT, requestId, result }, target);
	};

	window.addEventListener('message', handler);
	return () => window.removeEventListener('message', handler);
}
