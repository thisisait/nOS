/** BFF · Iris send — one ToThalamus line onto the caller's own tab (x-iris-tab, from the
 *  stream's first event). SvelteKit's CSRF check covers form content-types only, so a
 *  cross-site text/plain POST would pass it: this route wants same-origin JSON or 403. */
import { error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { MAX_LINE, fromThisSite, sendLine } from '$lib/server/thalamus';

export const POST: RequestHandler = async ({ request, url, locals }) => {
	if (!locals.identity.authenticated) error(401, 'unauthenticated');
	if (!fromThisSite(request, url, true)) error(403, 'not from this site');
	const type = (request.headers.get('content-type') ?? '').split(';')[0].trim().toLowerCase();
	if (type !== 'application/json') error(403, 'application/json only');
	if (Number(request.headers.get('content-length') ?? 0) > MAX_LINE) error(413, 'over 1 MiB');
	const text = await request.text();
	if (text.length > MAX_LINE) error(413, 'over 1 MiB');
	let msg: unknown;
	try {
		msg = JSON.parse(text);
	} catch {
		error(400, 'not JSON');
	}
	if (!msg || typeof msg !== 'object' || Array.isArray(msg)) error(400, 'not a message');
	// Re-serialised so a pretty-printed body cannot split into two wire lines.
	const r = sendLine(locals.identity, request.headers.get('x-iris-tab') ?? '', JSON.stringify(msg));
	if (r === 'no tab') error(409, 'no open Iris tab by that id');
	if (r === 'not yours') error(403, 'not your tab');
	return new Response(null, { status: 204 });
};
