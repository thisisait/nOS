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
	async stat(uid: string, path: string): Promise<unknown> {
		const u = new URL(VFS_BASE() + '/stat');
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
	},
	async mkdir(uid: string, path: string): Promise<unknown> {
		return asJson(
			await fetch(VFS_BASE() + '/mkdir', {
				method: 'POST',
				headers: boneHeaders(true),
				body: JSON.stringify({ uid, path })
			})
		);
	},
	async move(uid: string, src: string, dst: string): Promise<unknown> {
		return asJson(
			await fetch(VFS_BASE() + '/move', {
				method: 'POST',
				headers: boneHeaders(true),
				body: JSON.stringify({ uid, src, dst })
			})
		);
	},
	async copy(uid: string, src: string, dst: string): Promise<unknown> {
		return asJson(
			await fetch(VFS_BASE() + '/copy', {
				method: 'POST',
				headers: boneHeaders(true),
				body: JSON.stringify({ uid, src, dst })
			})
		);
	},
	async del(uid: string, path: string): Promise<unknown> {
		return asJson(
			await fetch(VFS_BASE() + '/delete', {
				method: 'POST',
				headers: boneHeaders(true),
				body: JSON.stringify({ uid, path })
			})
		);
	},
	/** Streamed upload → Bone POST /upload (raw body, capped upstream). Returns
	 *  the raw upstream Response so the caller can surface Bone's status/body. */
	async upload(uid: string, path: string, filename: string, body: BodyInit): Promise<Response> {
		const u = new URL(VFS_BASE() + '/upload');
		u.searchParams.set('uid', uid);
		u.searchParams.set('path', path);
		u.searchParams.set('filename', filename);
		return fetch(u, {
			method: 'POST',
			headers: { authorization: `Bearer ${VFS_TOKEN()}` },
			body,
			// Node fetch requires duplex when the body is a stream.
			...(typeof body === 'object' && body !== null && 'getReader' in body
				? { duplex: 'half' }
				: {})
		} as RequestInit);
	},
	/** Streamed download ← Bone GET /download. Returns the raw upstream Response
	 *  so the BFF can pipe the body + filename straight to the browser. */
	async download(uid: string, path: string): Promise<Response> {
		const u = new URL(VFS_BASE() + '/download');
		u.searchParams.set('uid', uid);
		u.searchParams.set('path', path);
		return fetch(u, { headers: boneHeaders() });
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

// ── KEAP DataTables — WRITE path (agent RW token; gated in the BFF) ───────────
// Reads use NOS_KEAP_API_TOKEN (RO); writes use a SEPARATE NOS_KEAP_API_TOKEN_RW
// so the shell holds least privilege for the read path. The BFF is the RBAC gate
// (manager+ tier only) — these helpers just carry the RW bearer to KEAP.

const KEAP_TOKEN_RW = () => env.NOS_KEAP_API_TOKEN_RW ?? '';

/** True when a write token is present (and KEAP is configured). */
export function keapWriteConfigured(): boolean {
	return keapConfigured() && Boolean(KEAP_TOKEN_RW());
}

function keapRwHeaders(): Record<string, string> {
	return { authorization: `Bearer ${KEAP_TOKEN_RW()}`, 'content-type': 'application/json' };
}

/** Table definition (columns/schema) — GET /agent/v1/tables/:slug (RO). */
export async function keapTableDef(slug: string): Promise<unknown> {
	const u = new URL(`${KEAP_TABLES()}/${encodeURIComponent(slug)}`);
	const h: Record<string, string> = {};
	if (KEAP_TOKEN()) h['authorization'] = `Bearer ${KEAP_TOKEN()}`;
	return asJson(await fetch(u, { headers: h }));
}

/** Upsert a row — POST /agent/v1/tables/:slug/rows (RW). `row` is the flat cell
 *  bag keyed by column (the KEAP agent surface un-wraps it). */
export async function keapUpsertRow(slug: string, row: Record<string, unknown>): Promise<unknown> {
	const u = new URL(`${KEAP_TABLES()}/${encodeURIComponent(slug)}/rows`);
	return asJson(
		await fetch(u, { method: 'POST', headers: keapRwHeaders(), body: JSON.stringify(row) })
	);
}

/** Create-or-return a table — POST /agent/v1/tables (RW). */
export async function keapCreateTable(body: Record<string, unknown>): Promise<unknown> {
	return asJson(
		await fetch(KEAP_TABLES(), {
			method: 'POST',
			headers: keapRwHeaders(),
			body: JSON.stringify(body)
		})
	);
}

// ── Local LLM (command-palette "ask") ────────────────────────────────────────
// Talks to the host Ollama on loopback (MLX backend). No token: loopback-only,
// reached via host.docker.internal. The model is either pinned by env or
// auto-picked from the installed set (first non-embedding model) so the palette
// works with whatever chat model the host has pulled — never a hardcoded tag,
// never a mock answer. If nothing chat-capable is installed, `configured:false`.

const OLLAMA_URL = () => env.NOS_OLLAMA_URL ?? 'http://host.docker.internal:11434';

async function pickModel(): Promise<string | null> {
	const pinned = (env.NOS_ASK_MODEL ?? '').trim();
	if (pinned) return pinned;
	try {
		const r = await fetch(OLLAMA_URL() + '/api/tags');
		if (!r.ok) return null;
		const data = (await r.json()) as { models?: Array<{ name?: string }> };
		const names = (data.models ?? []).map((m) => m.name ?? '').filter(Boolean);
		// Exclude embedding models — they can't answer a chat prompt.
		return names.find((n) => !/embed|nomic|bge|minilm/i.test(n)) ?? null;
	} catch {
		return null;
	}
}

export interface AskResult {
	configured: boolean;
	model?: string;
	answer?: string;
	note?: string;
}

/** One-shot prompt → local LLM completion. Bounded (num_predict) so the palette
 *  stays snappy; non-streaming for a simple request/response. */
export async function ask(prompt: string): Promise<AskResult> {
	const model = await pickModel();
	if (!model) {
		return {
			configured: false,
			note: 'No local chat model is installed on the host Ollama. Pull one (e.g. `ollama pull qwen2.5`) or set NOS_ASK_MODEL.'
		};
	}
	try {
		const r = await fetch(OLLAMA_URL() + '/api/generate', {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({
				model,
				prompt,
				stream: false,
				options: { num_predict: 512 }
			})
		});
		if (!r.ok) throw new UpstreamError(r.status, (await r.text()) || r.statusText);
		const data = (await r.json()) as { response?: string };
		return { configured: true, model, answer: (data.response ?? '').trim() };
	} catch (e) {
		if (e instanceof UpstreamError) throw e;
		throw new UpstreamError(502, 'local LLM unreachable');
	}
}
