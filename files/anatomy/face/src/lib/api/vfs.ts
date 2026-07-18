/** Real-file client over the Bone VFS (class-3 per-user tree). G5 extends with
 *  move/copy/upload/download; Wave 0 ships list/read/write. */
import { bffGet, bffPost } from './client';
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

// Re-export so native apps get the catalog type from one import surface.
export type { HubApp };
