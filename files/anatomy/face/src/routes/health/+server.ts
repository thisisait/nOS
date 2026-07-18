import { json } from '@sveltejs/kit';

/** Liveness probe — reachable before edge-trust (see hooks.server.ts). The
 *  Dockerfile HEALTHCHECK and the plugin post_compose wait_health hit this. */
export function GET() {
	return json({ status: 'ok', service: 'nos-face', version: '0.2.0' });
}
