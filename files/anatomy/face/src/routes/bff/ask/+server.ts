/** BFF · ask — the command palette's LLM bridge.
 *
 * POST { prompt } → a one-shot completion from the host's local LLM (Ollama MLX,
 * loopback). Requires an edge-trusted identity like every BFF route; the prompt
 * is the user's, the tokens/URL stay server-side. This is the "interact with an
 * LLM" half of the palette. Running arbitrary host COMMANDS is deliberately NOT
 * exposed here — that needs a gated, allowlisted, audited Bone endpoint
 * (destructive-op safety doctrine), tracked as a follow-up.
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { ask, UpstreamError } from '$lib/server/upstream';

export const POST: RequestHandler = async ({ request, locals }) => {
	if (!locals.identity.authenticated) throw error(401, 'unauthenticated');
	const body = (await request.json().catch(() => ({}))) as { prompt?: string };
	const prompt = (body.prompt ?? '').trim();
	if (!prompt) throw error(400, 'prompt required');
	if (prompt.length > 4000) throw error(413, 'prompt too long');
	try {
		return json(await ask(prompt));
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw e;
	}
};
