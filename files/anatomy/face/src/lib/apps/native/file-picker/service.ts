/**
 * File-picker service — the in-shell API.
 *
 * `openFilePicker(opts)` returns a Promise that resolves when the user picks a
 * file or cancels. It drives a Svelte store holding the *active* request; the
 * mounted <FilePicker /> host renders the dialog whenever a request is present
 * and calls `settlePicker(...)` to resolve the promise.
 *
 * One-at-a-time by design: a second `openFilePicker` while one is open cancels
 * the first (a picker is a modal). Pure store logic — no DOM here.
 */
import { writable, get } from 'svelte/store';
import type { FilePickerOptions, PickResult } from './types';
import { CANCELLED } from './types';

export interface PickerRequest {
	/** Monotonic id so the host can key/re-render per request. */
	id: number;
	opts: Required<Pick<FilePickerOptions, 'startPath' | 'uploadDir'>> & FilePickerOptions;
	settle: (result: PickResult) => void;
}

export const activePicker = writable<PickerRequest | null>(null);

let seq = 0;

/** Open the picker and resolve with the user's choice (or `CANCELLED`). */
export function openFilePicker(opts: FilePickerOptions = {}): Promise<PickResult> {
	// A picker is modal — supersede any in-flight request.
	const inflight = get(activePicker);
	if (inflight) inflight.settle(CANCELLED);

	return new Promise<PickResult>((resolve) => {
		seq += 1;
		activePicker.set({
			id: seq,
			opts: {
				title: opts.title ?? 'Choose a file',
				startPath: opts.startPath ?? 'documents',
				uploadDir: opts.uploadDir ?? 'inbox',
				allowUpload: opts.allowUpload ?? true,
				allowDirectories: opts.allowDirectories ?? false
			},
			settle: resolve
		});
	});
}

/** Resolve the given request and clear the active picker (host calls this). */
export function settlePicker(req: PickerRequest, result: PickResult): void {
	req.settle(result);
	// Only clear if this request is still the active one (guard against races).
	activePicker.update((cur) => (cur && cur.id === req.id ? null : cur));
}
