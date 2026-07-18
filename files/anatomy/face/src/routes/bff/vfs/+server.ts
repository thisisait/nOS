/** BFF · VFS. uid pinned from the identity; Bone enforces realpath-∈-scope +
 *  (G1) filename/UTF-8 hardening. G5 adds stat/mkdir/move/copy/delete +
 *  streaming upload/download ops (all additive — `list`/`read`/`write` behave
 *  exactly as before). The browser never supplies uid. */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { vfs, UpstreamError } from '$lib/server/upstream';

export const GET: RequestHandler = async ({ url, locals }) => {
	const uid = locals.identity.uid;
	const op = url.searchParams.get('op') ?? 'list';
	const path = url.searchParams.get('path') ?? 'documents';
	try {
		if (op === 'download') {
			const res = await vfs.download(uid, path);
			if (!res.ok) throw error(res.status, (await res.text()) || res.statusText);
			// Pipe the upstream body straight to the browser. Force an attachment
			// disposition with a basenamed filename (no path/UTF-8 injection).
			const name = (path.split('/').pop() || 'download').replace(/["\\\r\n]/g, '_');
			const headers = new Headers();
			headers.set('content-type', res.headers.get('content-type') ?? 'application/octet-stream');
			const len = res.headers.get('content-length');
			if (len) headers.set('content-length', len);
			headers.set('content-disposition', `attachment; filename="${name}"`);
			return new Response(res.body, { status: 200, headers });
		}
		const out =
			op === 'read'
				? await vfs.read(uid, path)
				: op === 'stat'
					? await vfs.stat(uid, path)
					: await vfs.list(uid, path);
		return json(out);
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw e;
	}
};

type VfsPost =
	| { op: 'write'; path: string; content: string }
	| { op: 'mkdir'; path: string }
	| { op: 'delete'; path: string }
	| { op: 'move'; src: string; dst: string }
	| { op: 'copy'; src: string; dst: string };

export const POST: RequestHandler = async ({ request, url, locals }) => {
	const uid = locals.identity.uid;
	try {
		// Upload is a raw-body stream (query-param addressed), not a JSON op.
		if (url.searchParams.get('op') === 'upload') {
			const path = url.searchParams.get('path') ?? 'documents';
			const filename = url.searchParams.get('filename') ?? 'upload.bin';
			if (!request.body) throw error(400, 'empty upload body');
			const res = await vfs.upload(uid, path, filename, request.body);
			const text = await res.text();
			if (!res.ok) throw error(res.status, text || res.statusText);
			return new Response(text || '{}', {
				status: 200,
				headers: { 'content-type': 'application/json' }
			});
		}

		const body = (await request.json()) as VfsPost;
		let out: unknown;
		switch (body.op) {
			case 'write':
				out = await vfs.write(uid, body.path, body.content ?? '');
				break;
			case 'mkdir':
				out = await vfs.mkdir(uid, body.path);
				break;
			case 'delete':
				out = await vfs.del(uid, body.path);
				break;
			case 'move':
				out = await vfs.move(uid, body.src, body.dst);
				break;
			case 'copy':
				out = await vfs.copy(uid, body.src, body.dst);
				break;
			default:
				throw error(400, 'unsupported op');
		}
		return json(out);
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw e;
	}
};
