/**
 * Server-only upstream clients — the ONLY place the Bone/Wing/KEAP tokens live.
 *
 * The browser never holds a token: it calls the BFF `/bff/*` endpoints, which
 * (having pinned `uid` from the edge-trusted identity) call these helpers. Bone
 * binds loopback; the container reaches it via host.docker.internal.
 *
 * This module MUST NOT be imported from client code — `$env/dynamic/private`
 * and the tokens would leak. SvelteKit enforces that for `$lib/server/*`.
 */
import { env } from '$env/dynamic/private';

const VFS_BASE = () => env.NOS_VFS_API_URL ?? 'http://host.docker.internal:8099/api/v1/vfs';
const US_BASE = () =>
	(env.NOS_VFS_API_URL ?? 'http://host.docker.internal:8099/api/v1/vfs').replace(
		/\/vfs$/,
		'/userstate'
	);
const HUB_URL = () => env.NOS_HUB_API_URL ?? 'http://host.docker.internal:9000/api/v1/hub/systems';
const KEAP_TABLES = () => env.NOS_KEAP_TABLES_URL ?? 'http://host.docker.internal:8790/api/tables';

const VFS_TOKEN = () => env.NOS_VFS_API_TOKEN ?? '';
const WING_EDGE = () => env.WING_EDGE_TOKEN ?? '';
const KEAP_TOKEN = () => env.NOS_KEAP_API_TOKEN ?? '';

function boneHeaders(json = false): Record<string, string> {
	const h: Record<string, string> = { authorization: `Bearer ${VFS_TOKEN()}` };
	if (json) h['content-type'] = 'application/json';
	return h;
}

async function asJson(r: Response): Promise<unknown> {
	const text = await r.text();
	if (!r.ok) {
		throw new UpstreamError(r.status, text || r.statusText);
	}
	return text ? JSON.parse(text) : {};
}

export class UpstreamError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
	}
}

// ── Bone VFS ──────────────────────────────────────────────────────────────────

export const vfs = {
	async list(uid: string, path: string): Promise<unknown> {
		const u = new URL(VFS_BASE() + '/list');
		u.searchParams.set('uid', uid);
		u.searchParams.set('path', path);
		return asJson(await fetch(u, { headers: boneHeaders() }));
	},
	async read(uid: string, path: string): Promise<unknown> {
		const u = new URL(VFS_BASE() + '/read');
		u.searchParams.set('uid', uid);
		u.searchParams.set('path', path);
		return asJson(await fetch(u, { headers: boneHeaders() }));
	},
	async write(uid: string, path: string, content: string): Promise<unknown> {
		return asJson(
			await fetch(VFS_BASE() + '/write', {
				method: 'POST',
				headers: boneHeaders(true),
				body: JSON.stringify({ uid, path, content })
			})
		);
	}
};

// ── Bone user-state ────────────────────────────────────────────────────────────

export const userstate = {
	async get(uid: string, ns: string, key: string): Promise<unknown> {
		const u = new URL(US_BASE() + '/get');
		u.searchParams.set('uid', uid);
		u.searchParams.set('ns', ns);
		u.searchParams.set('key', key);
		return asJson(await fetch(u, { headers: boneHeaders() }));
	},
	async list(uid: string, ns: string): Promise<unknown> {
		const u = new URL(US_BASE() + '/list');
		u.searchParams.set('uid', uid);
		u.searchParams.set('ns', ns);
		return asJson(await fetch(u, { headers: boneHeaders() }));
	},
	async set(uid: string, ns: string, key: string, value: unknown): Promise<unknown> {
		return asJson(
			await fetch(US_BASE() + '/set', {
				method: 'POST',
				headers: boneHeaders(true),
				body: JSON.stringify({ uid, ns, key, value })
			})
		);
	},
	async del(uid: string, ns: string, key: string): Promise<unknown> {
		return asJson(
			await fetch(US_BASE() + '/delete', {
				method: 'POST',
				headers: boneHeaders(true),
				body: JSON.stringify({ uid, ns, key })
			})
		);
	}
};

// ── Wing hub catalog (public GET; edge token passed defensively) ─────────────

export async function hubSystems(): Promise<unknown> {
	const h: Record<string, string> = {};
	if (WING_EDGE()) h['x-wing-edge-token'] = WING_EDGE();
	return asJson(await fetch(HUB_URL(), { headers: h }));
}

// ── KEAP DataTables (config catalog SoT; G2 fleshes out the row shape) ────────

export async function keapTableRows(slug: string, uid: string): Promise<unknown> {
	const u = new URL(`${KEAP_TABLES()}/${encodeURIComponent(slug)}/rows`);
	u.searchParams.set('uid', uid);
	const h: Record<string, string> = {};
	if (KEAP_TOKEN()) h['authorization'] = `Bearer ${KEAP_TOKEN()}`;
	return asJson(await fetch(u, { headers: h }));
}

export function keapConfigured(): boolean {
	return Boolean(env.NOS_KEAP_TABLES_URL);
}
