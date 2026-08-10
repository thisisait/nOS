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

// ── Wing Pulse API (Anatomy view — READ ONLY) ────────────────────────────────
//
// Bearer-authenticated, unlike the hub catalog above. The token is the Wing API
// token; it never leaves the server, and neither does most of what it fetches:
// `GET /api/v1/pulse_jobs` returns each job's `env_json` VERBATIM, and on this
// estate that is 57 live credential values across 23 of 25 jobs — Bone's HMAC
// secret, the Wing API token itself, agent client secrets, the MariaDB root
// password. The BFF therefore PROJECTS these responses onto an explicit
// allow-list of fields; nothing here may be proxied to a browser as-is.

const WING_API = () => env.NOS_WING_API_URL ?? 'http://host.docker.internal:9000/api/v1';
const WING_API_TOKEN = () => env.NOS_WING_API_TOKEN || process.env.NOS_WING_API_TOKEN || '';

/** True when the Wing API token is wired. A missing token is a CONFIGURATION
 *  fact the view must state, not an empty list it should render as calm. */
export function wingApiConfigured(): boolean {
	return Boolean(WING_API_TOKEN());
}

async function wingGet(path: string, params?: Record<string, string>): Promise<unknown> {
	const u = new URL(WING_API() + path);
	for (const [k, v] of Object.entries(params ?? {})) u.searchParams.set(k, v);
	const h: Record<string, string> = { authorization: `Bearer ${WING_API_TOKEN()}` };
	if (WING_EDGE()) h['x-wing-edge-token'] = WING_EDGE();
	return asJson(await fetch(u, { headers: h }));
}

/** Every registered Pulse job. Wing returns `jobs` as a MAP keyed by id — not
 *  an array; a caller that iterates it as one silently renders nothing. */
export async function pulseJobs(): Promise<unknown> {
	return wingGet('/pulse_jobs');
}

/** Per-job run aggregates. A job ABSENT from `summaries` has never fired. */
export async function pulseRunSummary(): Promise<unknown> {
	return wingGet('/pulse_runs/summary');
}

/** Recent runs, newest first. */
export async function pulseRuns(
	jobId?: string,
	limit = 50,
	since?: string,
	until?: string
): Promise<unknown> {
	const p: Record<string, string> = { limit: String(limit) };
	if (jobId) p.job_id = jobId;
	if (since) p.since = since;
	if (until) p.until = until;
	return wingGet('/pulse_runs', p);
}

/** §4b run-now: POST with an EMPTY body — Wing refuses anything else, and so
 *  does the BFF route in front of this. 202 + the recorded request. */
export async function pulseRunNow(jobId: string): Promise<unknown> {
	const u = new URL(WING_API() + '/pulse_jobs/' + encodeURIComponent(jobId) + '/run-now');
	const r = await fetch(u, {
		method: 'POST',
		headers: { authorization: `Bearer ${WING_API_TOKEN()}` }
	});
	return asJson(r);
}

/** Recent events — the audit spine. `actor_action_id` is the thread that ties
 *  a Pulse run to the events it produced, which is why Anatomy is one app. */
export async function wingEvents(params: Record<string, string> = {}): Promise<unknown> {
	return wingGet('/events', { limit: '60', ...params });
}

/** Notification inbox with its per-channel dispatch stamps. */
export async function wingNotifications(params: Record<string, string> = {}): Promise<unknown> {
	return wingGet('/notifications', { limit: '40', ...params });
}

// ── Bone (host daemon) ───────────────────────────────────────────────────────
//
// HONEST CREDENTIAL NOTE, measured 2026-08-05. The face holds BONE_VFS_TOKEN, a
// STATIC bearer that `vfs.py::require_vfs_token` accepts for the /api/v1/vfs
// router and nothing else. Bone's other read surfaces — /api/status,
// /api/services, /api/health/aggregate — are `require_scope("nos:state:read")`
// and want an Authentik-issued JWT; presenting the VFS token returns
// `401 invalid JWT header: Not enough segments`, verified.
//
// So the Bone view reads what the face can actually reach and SAYS SO about the
// rest. Rendering an empty services list because of a missing scope would be
// the ten-days-healthy defect with a different cause.

const BONE_BASE = () =>
	(env.NOS_VFS_API_URL ?? 'http://host.docker.internal:8099/api/v1/vfs').replace(
		/\/api\/v1\/vfs$/,
		''
	);

/** Liveness — the ONE ungated Bone endpoint. No token, by design: it answers
 *  "is Bone itself responding", which smoke probes and healthchecks need. */
export async function boneHealth(): Promise<unknown> {
	return asJson(await fetch(BONE_BASE() + '/api/health'));
}

/**
 * Prove the vein the face actually depends on carries traffic.
 *
 * Bone being alive does not mean the face can talk to it — the VFS token could
 * be unset or stale, and the file browser would then degrade quietly. One
 * `stat` of the caller's own root answers that, and it is the only Bone surface
 * the face is credentialed for.
 */
export async function boneVfsProbe(uid: string): Promise<{ ok: boolean; detail: string }> {
	if (!VFS_TOKEN())
		return { ok: false, detail: 'NOS_VFS_API_TOKEN is not set on the face container' };
	try {
		await vfs.stat(uid, '/');
		return { ok: true, detail: 'stat / succeeded with the face VFS bearer' };
	} catch (e) {
		const msg = e instanceof UpstreamError ? `${e.status} ${e.message}` : String(e);
		return { ok: false, detail: msg.slice(0, 300) };
	}
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

// `$env/dynamic/private` dropped this var at runtime in adapter-node when it was
// added to the compose env after the image was built (the RO token, present at
// build, reads fine; the newly-added RW one came back empty). Fall back to
// `process.env` — a purely-runtime server secret — so the write token is read
// regardless of SvelteKit's build-time key set. Server-only module, so safe.
const KEAP_TOKEN_RW = () => env.NOS_KEAP_API_TOKEN_RW || process.env.NOS_KEAP_API_TOKEN_RW || '';

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

/** List all tables — GET /agent/v1/tables (RO). Returns the enveloped
 *  `TableInfo[]` for the Tables app's sidebar. */
export async function keapListTables(): Promise<unknown> {
	const h: Record<string, string> = {};
	if (KEAP_TOKEN()) h['authorization'] = `Bearer ${KEAP_TOKEN()}`;
	return asJson(await fetch(KEAP_TABLES(), { headers: h }));
}

/** Public KEAP URL the browser iframes for the "Explore" app. A URL, not a
 *  secret (Authentik-gated, same cookie-domain session). process.env fallback
 *  mirrors the RW-token note above — robust against SvelteKit's build-time set. */
export function keapExploreUrl(): string {
	return env.NOS_KEAP_EXPLORE_URL || process.env.NOS_KEAP_EXPLORE_URL || '';
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

// ── Bone loop ledger (the run screen, 2026-08-06) ────────────────────────────
//
// Credential: BONE_LOOP_JUDGE_TOKEN — the loop's third channel (loopauth.py),
// evaluator identity ("Pulse / operator"), scopes {read, judge}. It is the
// right identity for a browser-triggered gate-set run because the endpoint it
// unlocks refuses every result-influencing parameter server-side; the face
// adds its own refusals on top (see /bff/loop/judge). Unset → the run screen
// says "unwired", never an empty ledger.

const LOOP_TOKEN = () => env.BONE_LOOP_JUDGE_TOKEN ?? '';

export function loopConfigured(): boolean {
	return LOOP_TOKEN().length >= 32;
}

function loopHeaders(json = false): Record<string, string> {
	const h: Record<string, string> = { authorization: `Bearer ${LOOP_TOKEN()}` };
	if (json) h['content-type'] = 'application/json';
	return h;
}

const LOOP_BASE = () => BONE_BASE() + '/api/v1/loop';

export const loop = {
	async proposals(limit = 100): Promise<unknown> {
		const u = new URL(LOOP_BASE() + '/proposals');
		u.searchParams.set('limit', String(limit));
		return asJson(await fetch(u, { headers: loopHeaders() }));
	},
	async judgeRuns(limit = 200, gateSet?: string): Promise<unknown> {
		const u = new URL(LOOP_BASE() + '/judge_runs');
		u.searchParams.set('limit', String(limit));
		if (gateSet) u.searchParams.set('gate_set', gateSet);
		return asJson(await fetch(u, { headers: loopHeaders() }));
	},
	async verdicts(limit = 100): Promise<unknown> {
		const u = new URL(LOOP_BASE() + '/verdicts');
		u.searchParams.set('limit', String(limit));
		return asJson(await fetch(u, { headers: loopHeaders() }));
	},
	/** 202 + job id. The ONLY selector is the gate-set NAME — Bone refuses
	 *  anything that supplies, hints at, or overrides a result. */
	async judge(gateSet: string): Promise<unknown> {
		return asJson(
			await fetch(LOOP_BASE() + '/judge', {
				method: 'POST',
				headers: loopHeaders(true),
				body: JSON.stringify({ gate_set: gateSet })
			})
		);
	},
	async judgeStatus(jobId: string): Promise<unknown> {
		return asJson(
			await fetch(LOOP_BASE() + '/judge/' + encodeURIComponent(jobId), {
				headers: loopHeaders()
			})
		);
	}
};
