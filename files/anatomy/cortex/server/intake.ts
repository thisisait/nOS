/**
 * Unified capture intake — ONE envelope for every data entry point.
 *
 * Before this file, KEAP had three write shapes on two auth planes (the
 * userscript's flat /api/metadata POST, the agent /agent/v1/captures POST,
 * plus ad-hoc fields). Every source now normalizes through
 * normalizeAndSaveCapture(): web UI / userscript, agents, and DEVICES —
 * AR glasses, mobile companions, field sensors — all land in the SAME
 * review queue with source + modality attribution. Curation stays human:
 * intake NEVER writes the curated layer or the objects corpus directly.
 *
 * The device path is /ingest/v1/capture:
 *   - its own bearer tier (KEAP_AGENT_TOKEN_CAPTURE — write-only intake;
 *     a lost device token cannot READ the knowledge base),
 *   - mounted BEFORE the identity middleware and it never reads
 *     X-Authentik-* headers, so the public bearer-only Traefik route
 *     (keap.<tld>/ingest/v1, no SSO middleware, rate-limited) cannot be
 *     used to forge a human identity,
 *   - idempotent on the client-supplied id (offline devices retry safely),
 *   - media arrives BY REFERENCE (media.url into RustFS/Nextcloud/anywhere);
 *     binary upload/presign is the planned phase 2.
 *
 * Envelope (POST /ingest/v1/capture):
 *   {
 *     id?: string                          // idempotency key (uuid)
 *     source: { kind: 'device'|'app'|'userscript'|'agent'|'web',
 *               name: string }             // device id / agent name / app
 *     modality?: 'url'|'text'|'geo'|'media'|'audio-transcript'
 *     title: string                        // the one human-readable line
 *     text?: string                        // note body / transcript
 *     url?: string
 *     domain?: string                      // derived from url when absent
 *     location?: { lat: number, lon: number, label?: string }
 *     media?: { url: string, mime?: string }
 *     capturedAt?: number                  // epoch seconds, device clock
 *     tags?: string[]
 *     metadata?: object                    // free extras (sensor data, …)
 *   }
 */
import crypto from 'node:crypto';
import type { Express, Request, Response, NextFunction, RequestHandler } from 'express';
import * as db from './db';
import { TOKEN_RW, TOKEN_CAPTURE, tokenEquals, bearerOf } from './tokens';

const ok = (res: Response, data?: unknown) => res.json({ success: true, data });
const fail = (res: Response, status: number, error: string) =>
  res.status(status).json({ success: false, error });

export type SourceKind = 'device' | 'app' | 'userscript' | 'agent' | 'web' | 'extension';

export interface CaptureEnvelope {
  id?: string;
  source: { kind: SourceKind; name: string };
  modality?: string;
  title: string;
  text?: string;
  url?: string;
  domain?: string;
  location?: { lat: number; lon: number; label?: string };
  media?: { url: string; mime?: string };
  capturedAt?: number;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

const SOURCE_KINDS: SourceKind[] = ['device', 'app', 'userscript', 'agent', 'web', 'extension'];
const MODALITIES = ['url', 'text', 'geo', 'media', 'audio-transcript'];

function inferModality(e: CaptureEnvelope): string {
  if (e.modality && MODALITIES.includes(e.modality)) return e.modality;
  if (e.media?.url) return 'media';
  if (e.location && !e.url && !e.text) return 'geo';
  if (e.url) return 'url';
  return 'text';
}

function domainOf(url?: string): string | undefined {
  if (!url) return undefined;
  try {
    return new URL(url).hostname;
  } catch {
    return undefined;
  }
}

/** Validate + normalize an envelope; throws Error with a 400-able message. */
export function parseEnvelope(body: unknown): CaptureEnvelope {
  if (!body || typeof body !== 'object') throw new Error('body must be a JSON object');
  // Structural view of the unvalidated wire body; every field below is still
  // runtime-checked or coerced before it enters the returned envelope.
  const b = body as Partial<CaptureEnvelope>;
  const src = b.source;
  if (!src || !SOURCE_KINDS.includes(src.kind) || typeof src.name !== 'string' || !src.name.trim()) {
    throw new Error(`source {kind: ${SOURCE_KINDS.join('|')}, name} is required`);
  }
  if (typeof b.title !== 'string' || !b.title.trim()) throw new Error('title is required');
  if (b.location && (typeof b.location.lat !== 'number' || typeof b.location.lon !== 'number')) {
    throw new Error('location requires numeric lat + lon');
  }
  if (b.media && typeof b.media.url !== 'string') {
    throw new Error('media requires url (media arrives by reference; binary upload is phase 2)');
  }
  return {
    id: typeof b.id === 'string' && b.id.trim() ? b.id : crypto.randomUUID(),
    source: { kind: src.kind, name: String(src.name).slice(0, 64) },
    modality: b.modality,
    title: String(b.title).slice(0, 300),
    text: b.text ? String(b.text).slice(0, 8000) : undefined,
    url: b.url ? String(b.url) : undefined,
    domain: b.domain ? String(b.domain) : undefined,
    location: b.location
      ? { lat: b.location.lat, lon: b.location.lon, label: b.location.label ? String(b.location.label).slice(0, 200) : undefined }
      : undefined,
    media: b.media ? { url: String(b.media.url), mime: b.media.mime ? String(b.media.mime) : undefined } : undefined,
    capturedAt: typeof b.capturedAt === 'number' ? b.capturedAt : undefined,
    tags: Array.isArray(b.tags) ? b.tags.slice(0, 20).map((t: unknown) => String(t).slice(0, 50)) : undefined,
    metadata: b.metadata && typeof b.metadata === 'object' ? b.metadata : undefined,
  };
}

/**
 * The single write path into the review queue. `attribution` is the storage
 * user_id — 'device:<name>' / 'agent:<name>' / the human uid. Idempotent on
 * envelope.id (saveMetadataApi upserts).
 */
export function normalizeAndSaveCapture(e: CaptureEnvelope, attribution: string): { id: string } {
  const modality = inferModality(e);
  db.saveMetadataApi(
    attribution,
    {
      id: e.id!,
      title: e.title,
      description: e.text,
      url: e.url,
      domain: e.domain ?? domainOf(e.url),
      metadata: {
        ...(e.metadata ?? {}),
        ...(e.location ? { location: e.location } : {}),
        ...(e.media ? { media: e.media } : {}),
        ...(e.capturedAt ? { capturedAt: e.capturedAt } : {}),
        ...(e.tags?.length ? { tags: e.tags } : {}),
      },
    },
    { source: e.source.kind, modality },
  );
  return { id: e.id! };
}

// ── Ingest surface (/ingest/v1/*) — device tier, no identity headers ─────────

function captureAuth(req: Request, res: Response, next: NextFunction) {
  if (!TOKEN_CAPTURE && !TOKEN_RW) return fail(res, 503, 'ingest disabled: no capture token configured');
  const token = bearerOf(req.headers.authorization);
  if (!token) return fail(res, 401, 'missing bearer token');
  const okToken =
    (TOKEN_CAPTURE && tokenEquals(token, TOKEN_CAPTURE)) || (TOKEN_RW && tokenEquals(token, TOKEN_RW));
  if (!okToken) return fail(res, 401, 'invalid token');
  next();
}

/**
 * nOS S2 DIFF (the ONLY change in this file; upstreamable, back-compatible).
 *
 * `bodyParser` is optional and defaults to a pass-through, so KEAP's own call
 * site — `registerIngestRoutes(app)` with a global `app.use(express.json())` —
 * is unaffected.
 *
 * The cortex organ has no app-wide body parser ON PURPOSE (see the long comment
 * at `server/index.ts`'s `jsonBody`): parsing in front of the bearer check means
 * an unauthenticated caller can reach express's error path with a malformed
 * body, and a body-parser SyntaxError is an ERROR, not a response — it skips
 * every handler and lands in the built-in final handler. Threading the parser
 * through here keeps it exactly where it belongs: AFTER `captureAuth`, so an
 * unauthorised body is never read, let alone parsed.
 */
export function registerIngestRoutes(app: Express, bodyParser?: RequestHandler, storeEpoch?: string) {
  const parse: RequestHandler = bodyParser ?? ((_req, _res, next) => next());

  // Device connectivity probe — minimal on purpose (no corpus stats on a
  // public, pre-auth surface).
  //
  // nOS S2 DIFF 2/2 (upstreamable, back-compatible: omit the argument and the
  // response is byte-identical to KEAP's). `storeEpoch` is an OPAQUE token that
  // changes when the store is REBUILT and at no other time — a digest of the
  // store identity, never the identity itself, so a pre-auth surface publishes
  // no corpus fact, only "am I still the store you were talking to".
  //
  // It exists because the consolidator's signature ledger lives in ~/.nos,
  // outside every store, and offers an item only to targets whose recorded
  // signature differs. A store that is wiped while its ledger survives is
  // therefore never re-fed: the source files are unchanged, so not one
  // `dp-<sha1>` capture row comes back, and the only cure was deleting a file
  // nothing documents. With an epoch the feeder notices by itself.
  app.get('/ingest/v1/health', (_req, res) =>
    ok(res, { status: 'OK', ...(storeEpoch ? { storeEpoch } : {}) }),
  );

  app.post('/ingest/v1/capture', captureAuth, parse, (req, res) => {
    let envelope: CaptureEnvelope;
    try {
      envelope = parseEnvelope(req.body);
    } catch (err) {
      return fail(res, 400, (err as Error).message);
    }
    // Attribution comes from the ENVELOPE (token tier is shared per class,
    // devices self-identify) — never from identity headers on this surface.
    const attribution = `${envelope.source.kind}:${envelope.source.name}`;
    const { id } = normalizeAndSaveCapture(envelope, attribution);
    res.status(201).json({ success: true, data: { id, queued: true, attribution } });
  });
}
