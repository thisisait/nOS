/**
 * Server-only upstream clients — the ONLY place the Bone/Wing tokens and the
 * KEAP proxy secret live.
 *
 * The browser never holds a token: it calls the BFF `/bff/*` endpoints, which
 * (having pinned `uid` from the edge-trusted identity) call these helpers. Bone
 * binds loopback; the container reaches it via host.docker.internal.
 *
 * This module MUST NOT be imported from client code — `$env/dynamic/private`
 * and the tokens would leak. SvelteKit enforces that for `$lib/server/*`.
 */
import { createHash } from 'node:crypto';
import { env } from '$env/dynamic/private';
import type { Identity } from '$lib/contracts';

const VFS_BASE = () => env.NOS_VFS_API_URL ?? 'http://host.docker.internal:8099/api/v1/vfs';
const US_BASE = () =>
	(env.NOS_VFS_API_URL ?? 'http://host.docker.internal:8099/api/v1/vfs').replace(
		/\/vfs$/,
		'/userstate'
	);
const HUB_URL = () => env.NOS_HUB_API_URL ?? 'http://host.docker.internal:9000/api/v1/hub/systems';
const KEAP_TABLES = () => env.NOS_KEAP_TABLES_URL ?? 'http://host.docker.internal:8091/api/tables';

const VFS_TOKEN = () => env.NOS_VFS_API_TOKEN ?? '';
const WING_EDGE = () => env.WING_EDGE_TOKEN ?? '';

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
	async upload(
		uid: string,
		path: string,
		filename: string,
		body: BodyInit,
		overwrite = false
	): Promise<Response> {
		const u = new URL(VFS_BASE() + '/upload');
		u.searchParams.set('uid', uid);
		u.searchParams.set('path', path);
		u.searchParams.set('filename', filename);
		if (overwrite) u.searchParams.set('overwrite', 'true');
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
	// ?listed=1: Wing's /hub filter + hub_card overlay, so the dock lists what /hub lists.
	const u = new URL(HUB_URL());
	u.searchParams.set('listed', '1');
	return asJson(await fetch(u, { headers: h }));
}

// ── Wing API, AS the end user (files/anatomy/contracts/face-wing.yml) ─────────
//
// One bearer: `face-bff`, the only Wing token that may speak for a user; Wing
// believes X-Nos-User-* on it alone and re-checks Tier 1 itself. Callers pass
// the hook-pinned identity. What it fetches never leaves the server as-is:
// `GET /api/v1/pulse_jobs` returns each job's `env_json` VERBATIM (57 live
// credentials across 23 of 25 jobs, measured), so the BFF PROJECTS every
// response onto an explicit allow-list of fields.

type WingUser = { uid: string; groups: string[] };

const WING_API = () => env.NOS_WING_API_URL ?? 'http://host.docker.internal:9000/api/v1';
const WING_BFF_TOKEN = () => env.NOS_WING_BFF_TOKEN || process.env.NOS_WING_BFF_TOKEN || '';

/** True when the face-bff token is wired. A missing token is a CONFIGURATION
 *  fact the view must state, not an empty list it should render as calm. */
export function wingBffConfigured(): boolean {
	return Boolean(WING_BFF_TOKEN());
}

async function wingGet(
	user: WingUser,
	path: string,
	params?: Record<string, string>
): Promise<unknown> {
	const u = new URL(WING_API() + path);
	for (const [k, v] of Object.entries(params ?? {})) u.searchParams.set(k, v);
	const h = asUser(user);
	if (WING_EDGE()) h['x-wing-edge-token'] = WING_EDGE();
	return asJson(await fetch(u, { headers: h }));
}

/** Every registered Pulse job. Wing returns `jobs` as a MAP keyed by id — not
 *  an array; a caller that iterates it as one silently renders nothing. */
export async function pulseJobs(user: WingUser): Promise<unknown> {
	return wingGet(user, '/pulse_jobs');
}

/** Per-job run aggregates. A job ABSENT from `summaries` has never fired. */
export async function pulseRunSummary(user: WingUser): Promise<unknown> {
	return wingGet(user, '/pulse_runs/summary');
}

/** Recent runs, newest first. */
export async function pulseRuns(
	user: WingUser,
	jobId?: string,
	limit = 50,
	since?: string,
	until?: string
): Promise<unknown> {
	const p: Record<string, string> = { limit: String(limit) };
	if (jobId) p.job_id = jobId;
	if (since) p.since = since;
	if (until) p.until = until;
	return wingGet(user, '/pulse_runs', p);
}

/** §4b run-now: POST with an EMPTY body — Wing refuses anything else, and so
 *  does the BFF route in front of this. An operator verb: Wing records user:<uid>. */
export async function pulseRunNow(user: WingUser, jobId: string): Promise<unknown> {
	const u = new URL(WING_API() + '/pulse_jobs/' + encodeURIComponent(jobId) + '/run-now');
	return asJson(await fetch(u, { method: 'POST', headers: asUser(user) }));
}

/** Recent events — the audit spine. `actor_action_id` is the thread that ties
 *  a Pulse run to the events it produced, which is why Anatomy is one app. */
export async function wingEvents(
	user: WingUser,
	params: Record<string, string> = {}
): Promise<unknown> {
	return wingGet(user, '/events', { limit: '60', ...params });
}

/** Notification inbox with its per-channel dispatch stamps. */
export async function wingNotifications(
	user: WingUser,
	params: Record<string, string> = {}
): Promise<unknown> {
	return wingGet(user, '/notifications', { limit: '40', ...params });
}

function asUser(user: WingUser, json = false): Record<string, string> {
	const h: Record<string, string> = {
		authorization: `Bearer ${WING_BFF_TOKEN()}`,
		'x-nos-user-uid': user.uid,
		'x-nos-user-groups': user.groups.join(',')
	};
	if (json) h['content-type'] = 'application/json';
	return h;
}

export const agentSessions = {
	async list(user: { uid: string; groups: string[] }, agent: string): Promise<unknown> {
		const u = WING_API() + '/agents/' + encodeURIComponent(agent) + '/sessions';
		return asJson(await fetch(u, { headers: asUser(user) }));
	},
	async open(
		user: { uid: string; groups: string[] },
		agent: string,
		body: { prompt?: string }
	): Promise<unknown> {
		const u = WING_API() + '/agents/' + encodeURIComponent(agent) + '/sessions';
		return asJson(
			await fetch(u, { method: 'POST', headers: asUser(user, true), body: JSON.stringify(body) })
		);
	},
	async get(user: { uid: string; groups: string[] }, uuid: string): Promise<unknown> {
		const u = WING_API() + '/agent-sessions/' + encodeURIComponent(uuid);
		return asJson(await fetch(u, { headers: asUser(user) }));
	}
};

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
 * Prove the link the face actually depends on carries traffic.
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

// ── KEAP DataTables — the human door, AS the person ─────────────────────────
// KEAP's /api/* believes X-Authentik-* only behind x-keap-proxy-secret (the
// secret Traefik injects), then enforces that person's table/row access and
// stamps writes user:<uid>. The face holds no estate bearer: identity comes
// from the hook-pinned locals.identity, and a missing one refuses here.

// The roadmap table predates id == slug (its id is a UUID, the same one
// tools/roadmap-*.py address); every other config table resolves as itself.
const TABLE_ID: Record<string, string> = {
	roadmap: '2d498264-bc9a-4324-9935-489e5e4d92f3'
};
const tableId = (slug: string): string => TABLE_ID[slug] ?? slug;
const tableUrl = (slug: string, tail = '') =>
	new URL(`${KEAP_TABLES()}/${encodeURIComponent(tableId(slug))}${tail}`);

// process.env fallback: adapter-node dropped a compose var added after the image
// was built from `$env/dynamic/private` (measured on the old RW token).
const KEAP_PROXY_SECRET = () =>
	env.KEAP_PROXY_SHARED_SECRET || process.env.KEAP_PROXY_SHARED_SECRET || '';

function keapAs(who: Identity, json = false): Record<string, string> {
	if (!who?.authenticated || !who.uid || !who.username) {
		throw new UpstreamError(401, 'KEAP call refused: no edge-trusted identity');
	}
	const secret = KEAP_PROXY_SECRET();
	// KEAP skips the hop check when its own secret is unset, so refuse here too.
	if (!secret) throw new UpstreamError(503, 'KEAP call refused: no proxy secret on the face');
	const h: Record<string, string> = {
		'x-keap-proxy-secret': secret,
		'x-authentik-username': who.username,
		'x-authentik-uid': who.uid,
		'x-authentik-groups': who.groups.join(',')
	};
	if (who.email) h['x-authentik-email'] = who.email;
	if (who.name) h['x-authentik-name'] = who.name;
	if (json) h['content-type'] = 'application/json';
	return h;
}

const data = (raw: unknown): unknown =>
	raw && typeof raw === 'object' && 'data' in raw ? (raw as { data: unknown }).data : raw;

type KeapRow = { id: string; values?: Record<string, unknown>; sharing?: unknown };
/** The /agent/v1 flat row shape every BFF consumer already reads. */
const flat = (r: KeapRow) => ({
	...r.values,
	__id: r.id,
	...(r.sharing ? { __sharing: r.sharing } : {})
});

// ponytail: 40 pages x 500 rows cap guards a cursor that never ends.
export async function keapTableRows(slug: string, who: Identity): Promise<unknown> {
	const rows: Record<string, unknown>[] = [];
	let cursor: string | undefined;
	for (let i = 0; i < 40; i++) {
		const u = tableUrl(slug, '/rows');
		u.searchParams.set('limit', '500');
		if (cursor) u.searchParams.set('cursor', cursor);
		const page = data(await asJson(await fetch(u, { headers: keapAs(who) }))) as {
			rows?: KeapRow[];
			nextCursor?: string;
		};
		rows.push(...(page.rows ?? []).map(flat));
		cursor = page.nextCursor;
		if (!cursor) break;
	}
	return { rows };
}

export function keapConfigured(): boolean {
	return Boolean(env.NOS_KEAP_TABLES_URL);
}

/** True when the face can prove the proxy hop (and KEAP is configured). */
export function keapWriteConfigured(): boolean {
	return keapConfigured() && Boolean(KEAP_PROXY_SECRET());
}

/** Table definition (columns/schema/view) — GET /api/tables/:id. */
export async function keapTableDef(slug: string, who: Identity): Promise<unknown> {
	return asJson(await fetch(tableUrl(slug), { headers: keapAs(who) }));
}

/** Upsert a row — POST /api/tables/:id/rows `{id?, values}`. `row` is the flat
 *  cell bag; its `__id` (else `slug`) names the row, as on the agent door. */
export async function keapUpsertRow(
	slug: string,
	row: Record<string, unknown>,
	who: Identity
): Promise<unknown> {
	const { __id, ...values } = row;
	const id = typeof __id === 'string' && __id ? __id : values.slug;
	const r = await fetch(tableUrl(slug, '/rows'), {
		method: 'POST',
		headers: keapAs(who, true),
		body: JSON.stringify({ ...(typeof id === 'string' && id ? { id } : {}), values })
	});
	return flat(data(await asJson(r)) as KeapRow);
}

/** UUIDv5 (URL namespace) of `name` — the human door takes uuid ids only. */
function uuidV5(name: string): string {
	const ns = Buffer.from('6ba7b8119dad11d180b400c04fd430c8', 'hex');
	const b = createHash('sha1').update(ns).update(name).digest().subarray(0, 16);
	b[6] = (b[6] & 0x0f) | 0x50;
	b[8] = (b[8] & 0x3f) | 0x80;
	const x = b.toString('hex');
	return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`;
}

/** Create a table — POST /api/tables, owned by the person. The id is derived
 *  from uid + typed slug (zod would strip a bare `slug`); a re-submit hits
 *  KEAP's duplicate-id 400, so read that id back and reuse the table. */
export async function keapCreateTable(
	body: Record<string, unknown>,
	who: Identity
): Promise<unknown> {
	const headers = keapAs(who, true);
	const { slug, ...rest } = body;
	const id =
		typeof slug === 'string' && slug ? uuidV5(`keap-face-table:${who.uid}/${slug}`) : undefined;
	try {
		return await asJson(
			await fetch(KEAP_TABLES(), {
				method: 'POST',
				headers,
				body: JSON.stringify(id ? { ...rest, id } : rest)
			})
		);
	} catch (e) {
		if (!id || !(e instanceof UpstreamError) || e.status !== 400) throw e;
		// No such table → the 400 was a real validation error: surface that one.
		const held = await keapTableDef(id, who).catch(() => Promise.reject(e));
		if (sameTable(held, rest)) return held;
		throw new UpstreamError(409, `"${slug}" already names a different table (${id})`);
	}
}

/** Same title, visibility and column keys: a re-submit, safe to reuse. */
function sameTable(held: unknown, sent: Record<string, unknown>): boolean {
	const t = ((held as { data?: unknown })?.data ?? held) as Record<string, unknown>;
	const keys = (x: Record<string, unknown>) =>
		JSON.stringify(
			((x?.schema as { columns?: { key?: unknown }[] })?.columns ?? []).map((c) => c.key)
		);
	return (
		t?.title === sent.title &&
		(t?.visibility ?? 'private') === (sent.visibility ?? 'private') &&
		keys(t) === keys(sent)
	);
}

/** Tables this person may read — GET /api/tables (enveloped `TableInfo[]`). */
export async function keapListTables(who: Identity): Promise<unknown> {
	return asJson(await fetch(KEAP_TABLES(), { headers: keapAs(who) }));
}

/** Public KEAP URL the browser iframes for the "Explore" app. A URL, not a
 *  secret (Authentik-gated, same cookie-domain session). process.env fallback
 *  mirrors the proxy-secret note above — robust against SvelteKit's build-time set. */
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
