/**
 * Table-write audit — closes bff/tables' `// TODO audit`.
 *
 * Bone's event ingestion (`files/anatomy/bone/events.py::verify_hmac`) wants
 * `X-Wing-Timestamp` + `X-Wing-Signature` (HMAC-SHA256 over `ts + "." + body`,
 * hex, no `sha256=` prefix required — Bone accepts either), the SAME scheme
 * `callback_plugins/wing_telemetry.py::_post_canonical` and
 * `files/anatomy/scripts/devlog_lib.py::emit_bone_event` already use. NOT the
 * bearer `boneHeaders()` pattern `$lib/server/upstream.ts` uses elsewhere —
 * Bone's `/api/v1/events` route checks the HMAC, not a bearer token, and
 * copying the nearby bearer helper here would ship a silent 401.
 *
 * `signEvent` is pure (no fetch, no env) so the HMAC math is testable without
 * a network. `postTableAudit` does the actual best-effort POST.
 */
import { createHmac } from 'node:crypto';
import { env } from '$env/dynamic/private';

export interface SignedEvent {
	body: string;
	headers: Record<string, string>;
}

/** Canonical body (sort_keys, no whitespace — matches wing_telemetry.py's
 *  `json.dumps(..., separators=(",", ":"), sort_keys=True)`) + the two HMAC
 *  headers. `nowSeconds` is injectable so a test can assert on a fixed ts. */
export function signEvent(
	secret: string,
	payload: Record<string, unknown>,
	nowSeconds: number = Math.floor(Date.now() / 1000)
): SignedEvent {
	const body = JSON.stringify(sortKeysDeep(payload));
	const ts = String(nowSeconds);
	const digest = createHmac('sha256', secret).update(`${ts}.${body}`).digest('hex');
	return {
		body,
		headers: {
			'Content-Type': 'application/json',
			'X-Wing-Timestamp': ts,
			'X-Wing-Signature': digest
		}
	};
}

/** `JSON.stringify` on a plain object is insertion-order, not sorted — sort
 *  every object's keys (recursively; arrays keep their order) so this
 *  reconstructs byte-identically regardless of how the caller built the
 *  payload, matching Python's `sort_keys=True`. */
function sortKeysDeep(v: unknown): unknown {
	if (Array.isArray(v)) return v.map(sortKeysDeep);
	if (v && typeof v === 'object') {
		const out: Record<string, unknown> = {};
		for (const k of Object.keys(v as Record<string, unknown>).sort()) {
			out[k] = sortKeysDeep((v as Record<string, unknown>)[k]);
		}
		return out;
	}
	return v;
}

const BONE_EVENTS_URL = () =>
	env.NOS_BONE_EVENTS_URL ?? 'http://host.docker.internal:8099/api/v1/events';
const HMAC_SECRET = () => env.WING_EVENTS_HMAC_SECRET || process.env.WING_EVENTS_HMAC_SECRET || '';

/** Best-effort: a table write must succeed regardless of whether the audit
 *  trail could be recorded (same non-blocking contract devlog_lib.py's
 *  `emit_bone_event` documents — "never raises"). Unconfigured secret is a
 *  silent no-op, not an error — same degrade as every other optional wiring
 *  in this BFF (KEAP unconfigured, Wing token unset, …). */
export async function postTableAudit(uid: string, slug: string, rowId: string): Promise<void> {
	const secret = HMAC_SECRET();
	if (!secret) return;
	const { body, headers } = signEvent(secret, {
		ts: new Date().toISOString(),
		type: 'table.upsert',
		run_id: `face-bff-${Date.now()}`,
		source: 'face',
		actor_id: uid,
		result: { slug, row_id: rowId }
	});
	try {
		await fetch(BONE_EVENTS_URL(), { method: 'POST', headers, body });
	} catch {
		/* audit failure must never fail the write it's auditing */
	}
}
