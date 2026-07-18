/** BFF · VFS. uid pinned from the identity; Bone enforces realpath-∈-scope +
 *  (G1) filename/UTF-8 hardening. G5 adds move/copy/upload/download ops. */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { vfs, UpstreamError } from '$lib/server/upstream';

export const GET: RequestHandler = async ({ url, locals }) => {
	const uid = locals.identity.uid;
	const op = url.searchParams.get('op') ?? 'list';
	const path = url.searchParams.get('path') ?? 'documents';
	try {
		const out = op === 'read' ? await vfs.read(uid, path) : await vfs.list(uid, path);
		return json(out);
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw e;
	}
};

export const POST: RequestHandler = async ({ request, locals }) => {
	const uid = locals.identity.uid;
	const body = (await request.json()) as { op: 'write'; path: string; content: string };
	try {
		if (body.op !== 'write') throw error(400, 'unsupported op');
		const out = await vfs.write(uid, body.path, body.content ?? '');
		return json(out);
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw e;
	}
};
