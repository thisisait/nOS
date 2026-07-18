/** Real-file client over the Bone VFS (class-3 per-user tree). G5 extends with
 *  stat/mkdir/move/copy/delete/upload/download; Wave 0 ships list/read/write.
 *
 *  Every call is same-origin to the BFF (`/bff/vfs`), which pins `uid` from the
 *  edge-trusted identity — the browser NEVER sends a uid. Additive only: the
 *  Wave-0 exports (`vfsList`/`vfsRead`/`vfsWrite`) are unchanged. */
import { bffGet, bffPost, ApiError } from './client';
import type { HubApp } from '$lib/contracts';

export interface VfsEntry {
	name: string;
	path: string;
	kind: 'dir' | 'file';
	size: number;
	mtime: number;
}

export async function vfsList(path = 'documents'): Promise<VfsEntry[]> {
	const r = await bffGet<{ entries: VfsEntry[] }>('/bff/vfs', { op: 'list', path });
	return r.entries ?? [];
}

export async function vfsRead(path: string): Promise<string> {
	const r = await bffGet<{ content: string }>('/bff/vfs', { op: 'read', path });
	return r.content ?? '';
}

export async function vfsWrite(path: string, content: string): Promise<void> {
	await bffPost('/bff/vfs', { op: 'write', path, content });
}

// ── G5 additions (VFS ops the file browser + picker need) ────────────────────

/** Metadata for a single entry (Bone GET /stat). */
export async function vfsStat(path: string): Promise<VfsEntry> {
	return bffGet<VfsEntry>('/bff/vfs', { op: 'stat', path });
}

/** Create a directory (idempotent; Bone GET-less POST /mkdir). */
export async function vfsMkdir(path: string): Promise<void> {
	await bffPost('/bff/vfs', { op: 'mkdir', path });
}

/** Move/rename src → dst (Bone POST /move). */
export async function vfsMove(src: string, dst: string): Promise<void> {
	await bffPost('/bff/vfs', { op: 'move', src, dst });
}

/** Copy src → dst (Bone POST /copy; 409 if dst exists). */
export async function vfsCopy(src: string, dst: string): Promise<void> {
	await bffPost('/bff/vfs', { op: 'copy', src, dst });
}

/** Delete a file or directory tree (Bone POST /delete; root is refused). */
export async function vfsDelete(path: string): Promise<void> {
	await bffPost('/bff/vfs', { op: 'delete', path });
}

/** Upload a browser File into `dir` (from-device picker mode). Streams the raw
 *  body to the BFF, which proxies it to Bone's capped streaming /upload. The
 *  filename is taken from the File; Bone basenames it. */
export async function vfsUpload(dir: string, file: File): Promise<VfsEntry> {
	const u = new URL('/bff/vfs', location.origin);
	u.searchParams.set('op', 'upload');
	u.searchParams.set('path', dir);
	u.searchParams.set('filename', file.name);
	const r = await fetch(u, { method: 'POST', body: file });
	if (!r.ok) throw new ApiError(r.status, (await r.text()) || r.statusText);
	return (await r.json()) as VfsEntry;
}

/** A same-origin URL that streams a file download through the BFF. Use as an
 *  `<a href>` — the browser handles the save dialog; uid stays server-pinned. */
export function vfsDownloadUrl(path: string): string {
	const u = new URL('/bff/vfs', location.origin);
	u.searchParams.set('op', 'download');
	u.searchParams.set('path', path);
	return u.pathname + u.search;
}

// Re-export so native apps get the catalog type from one import surface.
export type { HubApp };
