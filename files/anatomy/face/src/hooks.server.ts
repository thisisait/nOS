/**
 * nOS-face BFF — the identity + anti-spoof boundary.
 *
 * Mirrors Wing's SEC-6 edge-trust (ForwardAuthUserStorage + BasePresenter::
 * enforceEdgeTrust) EXACTLY:
 *   1. Traefik's Authentik outpost injects X-Authentik-{uid,username,email,groups}.
 *   2. Traefik's `face-edge` middleware injects X-Face-Edge-Token (customRequest-
 *      Headers REPLACES any client value), so a peer on gated_net cannot forge it.
 *   3. This hook believes the Authentik headers ONLY when the edge token matches.
 *
 * `uid` is pinned here from the edge-trusted header and is the ONLY value passed
 * downstream to Bone (VFS/user-state) and KEAP. The browser can never set it.
 */
import { timingSafeEqual } from 'node:crypto';
import { env } from '$env/dynamic/private';
import type { Handle } from '@sveltejs/kit';
import { ANON, type Identity } from '$lib/contracts';

/** Timing-safe string compare that never short-circuits on length. */
function safeEqual(a: string, b: string): boolean {
	const ab = Buffer.from(a, 'utf8');
	const bb = Buffer.from(b, 'utf8');
	if (ab.length !== bb.length) {
		// Compare against self to keep timing uniform, then fail.
		timingSafeEqual(ab, ab);
		return false;
	}
	return timingSafeEqual(ab, bb);
}

function edgeTrusted(request: Request): boolean {
	const expected = env.FACE_EDGE_TOKEN ?? '';
	// If no edge token is configured (local dev), trust is implicit. In prod the
	// role always sets it (roles/pazny.face compose env).
	if (!expected) return true;
	const headerName = (env.FACE_EDGE_TOKEN_HEADER ?? 'x-face-edge-token').toLowerCase();
	const provided = request.headers.get(headerName) ?? '';
	return provided.length > 0 && safeEqual(provided, expected);
}

function readIdentity(request: Request, trusted: boolean): Identity {
	if (!trusted) return { ...ANON };
	const h = request.headers;
	const uid = (h.get('x-authentik-uid') ?? '').trim();
	if (!uid) return { ...ANON };
	const groups = (h.get('x-authentik-groups') ?? '')
		.split(/[|,]/)
		.map((g) => g.trim())
		.filter(Boolean);
	return {
		uid,
		username: (h.get('x-authentik-username') ?? uid).trim(),
		email: (h.get('x-authentik-email') ?? '').trim(),
		groups,
		authenticated: true
	};
}

export const handle: Handle = async ({ event, resolve }) => {
	// /health is always reachable (liveness probe rides before edge trust).
	if (event.url.pathname === '/health') {
		return resolve(event);
	}

	const trusted = edgeTrusted(event.request);
	if (env.FACE_EDGE_TOKEN && !trusted) {
		// A caller reached us without the edge token → cannot be trusted at all.
		return new Response('forbidden: missing edge trust', { status: 403 });
	}

	event.locals.identity = readIdentity(event.request, trusted);

	// BFF endpoints require a real identity — no anonymous data access.
	if (event.url.pathname.startsWith('/bff/') && !event.locals.identity.authenticated) {
		return new Response('unauthorized', { status: 401 });
	}

	return resolve(event);
};
