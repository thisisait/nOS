/** BFF · user-state. uid is pinned from the edge-trusted identity — never from
 *  the client. Namespace/key validation is Bone's job (it owns the regexes). */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { userstate, UpstreamError } from '$lib/server/upstream';

export const GET: RequestHandler = async ({ url, locals }) => {
	const uid = locals.identity.uid;
	const ns = url.searchParams.get('ns') ?? '';
	const key = url.searchParams.get('key');
	try {
		const out = key ? await userstate.get(uid, ns, key) : await userstate.list(uid, ns);
		return json(out);
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw e;
	}
};

export const POST: RequestHandler = async ({ request, locals }) => {
	const uid = locals.identity.uid;
	const body = (await request.json()) as {
		op: 'set' | 'delete';
		ns: string;
		key: string;
		value?: unknown;
	};
	try {
		const out =
			body.op === 'delete'
				? await userstate.del(uid, body.ns, body.key)
				: await userstate.set(uid, body.ns, body.key, body.value);
		return json(out);
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw e;
	}
};
