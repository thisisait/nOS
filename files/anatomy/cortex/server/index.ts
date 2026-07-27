/**
 * The Cortex organ daemon — LOCALLY AUTHORED (not a port). Build sequence step 7.
 *
 * A loopback-only Express process that boots the organ's own store and exposes
 * the cortex reasoning surface:
 *
 *   GET  /health                     unauthenticated liveness + the three drift axes
 *   GET  /agent/v1/health            the same handler, at KEAP's path (see below)
 *   POST /agent/v1/validate          agentAuth('ro') — typecheck a program, zero side effects
 *   GET  /agent/v1/validate/opcodes  agentAuth('ro') — the published registry Wing gates against
 *
 * and — since S2 (`docs/plans/cortex-corpus-parallel.md`) — the INGESTION half,
 * which exists so the organ can be fed the same corpus KEAP is fed, from the
 * same host sources, and the two can then be compared:
 *
 *   GET  /agent/v1/fs/status         agentAuth('ro') — roots, last pass, last REFUSAL
 *   POST /agent/v1/fs/sync           agentAuth('rw') — one mirror pass over the host tree
 *   GET  /agent/v1/objects           agentAuth('ro') — the id set, paged (KEAP's shape)
 *   GET  /agent/v1/objects/:id       agentAuth('ro') — one card, for the body hash
 *   GET  /agent/v1/graph             agentAuth('ro') — the TAXONOMY id set + edges
 *   GET  /agent/v1/captures          agentAuth('ro') — the review queue
 *   GET  /agent/v1/embeddings/pending agentAuth('ro') — the embed diff (model + dim)
 *   POST /agent/v1/embeddings        agentAuth('rw') — vectors back from the host job
 *   GET  /ingest/v1/health           unauthenticated device probe
 *   POST /ingest/v1/capture          capture-tier bearer — the consolidator's target
 *
 * Every one of these is KEAP's route at KEAP's path with KEAP's response shape,
 * lifted from `server/agent.ts` / `server/intake.ts`. That is not laziness: the
 * fan-out feeders and the nightly diff harness talk to BOTH daemons with ONE
 * client, and a shape that drifted would make a difference in the report
 * indistinguishable from a difference in the corpus.
 *
 * Still NOT here, and staying in KEAP: taxonomy CRUD, semantic search, relation
 * WRITES and candidate generation, tables, lint, curator, topics, promotions,
 * openapi.json, and the whole `/api` + SPA surface. (`/agent/v1/graph` is a
 * read of the relation tables, not a relations surface — see its own header for
 * why the diff harness needs it and why it is served whole rather than trimmed.) The 404 handler at the bottom says so in the
 * envelope rather than letting an unmounted path fall through to something that
 * looks like a server error.
 *
 * ── Import order is load-bearing ────────────────────────────────────────────
 *
 * `server/db.ts:29-30` resolves its data directory at MODULE LOAD:
 *
 *     const DATA_DIR = process.env.KEAP_DATA_DIR ?? …
 *     const DB_PATH  = path.join(DATA_DIR, 'keap.db')
 *
 * and `openStore()` is what SETS `KEAP_DATA_DIR` (from `CORTEX_STORE_PATH`).
 * ESM evaluates every static import before any top-level statement runs, so a
 * static `import { validateCortex } from './cortex-validate'` here would pull in
 * `./db` — and bind the wrong directory — before `main()` ever executed. The
 * daemon would then open `~/.keap/keap.db` (or whatever the ambient env said)
 * while reporting the configured path, which is a wrong-store bug that boots
 * cleanly and answers plausibly.
 *
 * So: every cortex module is imported DYNAMICALLY, after `openStore()`. This
 * file's only static imports are the two locally-authored modules that read no
 * database (`cortex-store`, `cortex-config`) and express itself. The same
 * lesson is recorded at `server/cortex-resolve.test.ts:21` and in
 * `cortex-store.ts`'s `openStore()`.
 *
 * ── The organ mints its own identity ────────────────────────────────────────
 *
 * `database.id` below is whatever `initDb()` minted for THIS store on first
 * boot. It is deliberately not KEAP's — see `cortex-store.ts` and
 * `docs/specs/cortex-full-scope-decision.md` ("Two corrections"). A binding
 * stamped by this daemon and a binding stamped by KEAP therefore disagree on
 * `databaseId` by construction, and that disagreement is the drift mechanism
 * working, not a defect to paper over.
 */
import { createHash } from 'node:crypto';
import express from 'express';
import type { Request, Response, NextFunction } from 'express';
import { openStore } from './cortex-store';

/** Loopback only. The organ is a host-local daemon; there is no path by which it
 *  should be reachable off the box without something in front deciding so
 *  explicitly (design §2: the Traefik file-provider route is opt-in, default off). */
const HOST = process.env.CORTEX_BIND_HOST ?? '127.0.0.1';
const PORT = Number(process.env.PORT ?? process.env.CORTEX_PORT ?? 8098);

/**
 * Whether the boot runs the git ingest path.
 *
 * DEFAULT OFF. The Ansible role materialises once at build time
 * (`npm run store:materialise`, build sequence step 9) and the daemon then just
 * opens what is there — a restart must not re-walk 107 canonical files before
 * it can answer a health probe. `CORTEX_MATERIALISE_ON_BOOT=1` is the escape
 * hatch for a store that was provisioned empty.
 */
const MATERIALISE_ON_BOOT = process.env.CORTEX_MATERIALISE_ON_BOOT === '1';

/**
 * Token env aliasing — the ONLY reason this exists is to keep `server/tokens.ts`
 * byte-identical to KEAP's.
 *
 * `tokens.ts` reads `KEAP_AGENT_TOKEN_RO` / `_RW` at module load and is ported
 * VERBATIM (the bearer comparison is security-critical: sha256 →
 * `crypto.timingSafeEqual`, never `===`). The organ's own deployment vocabulary
 * is `cortex_ro_token` / `cortex_rw_token` (design §2), so this maps
 * `CORTEX_TOKEN_RO`/`_RW` onto the names the ported module reads, BEFORE it is
 * imported. Setting `KEAP_AGENT_TOKEN_*` directly still works and wins nothing —
 * the CORTEX_* name takes precedence when both are set, because it is the one
 * the role will own.
 *
 * This is a config seam, not a logic change: no token is compared here, and the
 * fail-closed rule below is the ported one.
 */
function aliasTokenEnv(env: NodeJS.ProcessEnv): void {
  if (env.CORTEX_TOKEN_RO?.trim()) env.KEAP_AGENT_TOKEN_RO = env.CORTEX_TOKEN_RO;
  if (env.CORTEX_TOKEN_RW?.trim()) env.KEAP_AGENT_TOKEN_RW = env.CORTEX_TOKEN_RW;
  // S2: the capture tier. The consolidator fan-out POSTs /ingest/v1/capture to
  // both targets, and it MUST hold two DIFFERENT secrets under two DIFFERENT
  // names (§2.1) — one env name meaning two secrets on one host is how a write
  // token reaches the wrong daemon. Inside the organ's own process the ported
  // `tokens.ts` still reads the KEAP_* name; the plist sets the CORTEX_* one.
  if (env.CORTEX_TOKEN_CAPTURE?.trim()) env.KEAP_AGENT_TOKEN_CAPTURE = env.CORTEX_TOKEN_CAPTURE;
}

const ok = (res: Response, data?: unknown) => res.json({ success: true, data });
const fail = (res: Response, status: number, error: string) =>
  res.status(status).json({ success: false, error });

type AgentScope = 'ro' | 'rw';

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      agentScope?: AgentScope;
      agentName?: string;
    }
  }
}

async function main(): Promise<void> {
  // ── 1. the store (build sequence steps 4 + 6, unchanged) ───────────────────
  const store = await openStore({ materialise: MATERIALISE_ON_BOOT });
  const { db, taxonomy, config, facts } = store;

  // ── 2. the cortex modules, AFTER the store has fixed KEAP_DATA_DIR ─────────
  aliasTokenEnv(process.env);
  // S2: same seam, same one-way flow — CORTEX_FS_* onto the KEAP_FS_* names the
  // ported fs-sync reads, BEFORE `./fs-sync` is imported (it resolves its roots
  // at module load, exactly as `db.ts` resolves its data directory).
  const { aliasFsEnv } = await import('./cortex-fs');
  aliasFsEnv(process.env);
  const { TOKEN_RO, TOKEN_RW, tokenEquals } = await import('./tokens');
  const { CORTEX_CONTRACT_VERSION, cortexRegistryHash, listOpcodes } = await import('./cortex-opcodes');
  const { cortexOntologyVersion } = await import('./cortex-ontology-version');
  const { validateCortex } = await import('./cortex-validate');
  const { cortexValidateRequestSchema } = await import('../shared/contracts/cortex');
  const { buildVersion } = await import('./build-version');
  const { fsSyncStatus, startFsSync, syncAllFs } = await import('./fs-sync');
  const { EMBED_MODEL, EMBED_DIM, pendingEmbeddings } = await import('./embeddings');
  const { registerIngestRoutes } = await import('./intake');

  /**
   * Bearer auth — LIFTED from KEAP `server/agent.ts:63-81`, behaviour for
   * behaviour. Read the three rules off it rather than off this comment:
   *
   *   1. FAIL CLOSED. Neither token configured ⇒ 503 for the whole surface. The
   *      organ never invents an implicit identity because nobody gave it one;
   *      an unconfigured agent surface is a DISABLED surface, not an open one.
   *   2. The comparison is `tokenEquals` (sha256 → `crypto.timingSafeEqual`),
   *      never `===`. Both operands are hashed first so the compare is over
   *      fixed-length buffers — `timingSafeEqual` throws on a length mismatch,
   *      and a throw that depends on the attacker's token length is itself an
   *      oracle.
   *   3. RW satisfies an 'ro' requirement; 'ro' does not satisfy 'rw'.
   *
   * `x-keap-agent` is self-asserted and unbound to the token. It is recorded so
   * a log line can carry it and believed by nothing.
   */
  function agentAuth(required: AgentScope) {
    return (req: Request, res: Response, next: NextFunction) => {
      if (!TOKEN_RO && !TOKEN_RW) return fail(res, 503, 'agent surface disabled: no agent token configured');
      const auth = req.headers.authorization ?? '';
      const token = auth.startsWith('Bearer ') ? auth.slice(7) : null;
      if (!token) return fail(res, 401, 'missing bearer token');

      let scope: AgentScope | null = null;
      if (TOKEN_RW && tokenEquals(token, TOKEN_RW)) scope = 'rw';
      else if (TOKEN_RO && tokenEquals(token, TOKEN_RO)) scope = 'ro';
      if (!scope) return fail(res, 401, 'invalid token');
      if (required === 'rw' && scope !== 'rw') return fail(res, 403, 'write scope required');

      req.agentScope = scope;
      req.agentName = String(req.headers['x-keap-agent'] ?? 'unknown').slice(0, 64);
      next();
    };
  }

  const app = express();
  // 2 MB is the TRANSPORT ceiling and is cited as such by
  // shared/contracts/cortex.ts: §3.6's 4096-char program cap is a SEMANTIC bound
  // reported as a typed `program_too_large` entry inside a 200, and
  // `analyzeCortex` checks the length before tokenizing, so an oversize body is
  // never scanned. Keep the two limits distinct — collapsing them turns a
  // repairable report into an opaque 413.
  //
  // MOUNTED PER ROUTE, BEHIND `agentAuth`, not app-wide. app.use()ing it puts
  // body parsing in front of the bearer check, and a body-parser SyntaxError is
  // an ERROR, not a response: it skips every normal handler below it and lands
  // in express's built-in final handler, which answers text/html carrying the
  // full stack whenever NODE_ENV !== 'production'. That broke two contracts at
  // once — the envelope one stated at the 404 handler, and rule 1 of agentAuth
  // ("neither token configured ⇒ 503 for the whole surface"), because an
  // unauthenticated caller could get an HTML stack trace with absolute host
  // paths out of a daemon whose agent surface was DISABLED. Parsing after the
  // auth middleware means an unauthorised body is never read, let alone parsed.
  const jsonBody = express.json({ limit: '2mb' });

  // ── /health ────────────────────────────────────────────────────────────────
  /**
   * UNAUTHENTICATED, and deliberately still answers when the agent surface is
   * disabled — it reports `surface: 'disabled'` instead. A liveness probe that
   * 503s because no token was configured would make a correctly fail-closed
   * organ indistinguishable from a dead one, which is the wrong way round: the
   * process is up and is refusing on purpose.
   *
   * `binding` is the addition to KEAP's shape and it is the point of the
   * endpoint: the SAME three axes `ast.binding` stamps into every validated
   * program, published where an operator, the Ansible verify step and Wing can
   * read them without POSTing a program. `ontology.version` and `database` are
   * kept in KEAP's nested positions as well so a client ported from KEAP's
   * `/agent/v1/health` keeps working.
   *
   * `contracts` declares `cortex` ONLY. KEAP's health also declares
   * `selfmodel: 1`; this organ does not implement the slug-tree contract (no
   * `/agent/v1/objects`, no corpus), and declaring a contract you do not serve
   * is worse than declaring nothing.
   */
  const health = (_req: Request, res: Response) => {
    const stats = db.corpusStats();
    ok(res, {
      status: 'OK',
      organ: 'pazny.cortex',
      contracts: { cortex: CORTEX_CONTRACT_VERSION },
      version: buildVersion(),
      surface: TOKEN_RO || TOKEN_RW ? 'enabled' : 'disabled',
      // The three drift axes, together, in the shape `ast.binding` carries them.
      binding: {
        ontologyVersion: cortexOntologyVersion(),
        databaseId: db.getDbIdentity()?.id ?? null,
        opcodeRegistryHash: cortexRegistryHash(),
      },
      store: {
        path: config.dbPath,
        materialisedOnBoot: MATERIALISE_ON_BOOT,
        spineInSync: store.materialise.spineInSync,
        annOutcome: facts.ann.outcome,
        vectorSearchAvailable: db.vectorSearchAvailable(),
      },
      corpus: { taxonomyNodes: taxonomy.taxonomyNodeCount(), ...stats },
      embeddings: db.embeddingStats(),
      database: db.getDbIdentity(),
      ontology: { ...db.ontologyStats(), version: cortexOntologyVersion() },
    });
  };
  app.get('/health', health);
  // KEAP's path for the same facts, so a caller ported from KEAP does not have
  // to learn a new one at the same moment it learns a new host and port.
  app.get('/agent/v1/health', health);

  // ── POST /agent/v1/validate ────────────────────────────────────────────────
  // LIFTED from KEAP `server/agent.ts:1197-1206`.
  //
  // agentAuth('ro'), NOT 'rw': the endpoint has ZERO side effects — no row, no
  // proposal, no embedding, no cache warm — and requiring a write token to
  // typecheck would force the executor to hold write credentials for a read
  // operation, which is exactly backwards.
  //
  // This route reads NOTHING from `req.agentName`. That header is self-asserted
  // and unbound to the token; it may be logged, it may not be believed, and no
  // scope, filter or limit here keys on it.
  app.post('/agent/v1/validate', agentAuth('ro'), jsonBody, (req, res) => {
    const parsed = cortexValidateRequestSchema.safeParse(req.body);
    // Phase 1. A malformed REQUEST is a transport error; a malformed PROGRAM is
    // data (§3.1), and comes back as a 200 report with typed entries.
    if (!parsed.success) return fail(res, 400, parsed.error.issues[0]?.message ?? 'invalid request');
    ok(res, validateCortex(parsed.data.source, parsed.data.ttlSeconds));
  });

  // ── GET /agent/v1/validate/opcodes ─────────────────────────────────────────
  // LIFTED from KEAP `server/agent.ts:1213-1219`. Wing fetches this at boot and
  // in CI and compares it against its handler map: handlers ⊉ opcodes → Wing
  // refuses to start (it would accept ASTs it cannot dispatch); handlers ⊃
  // opcodes → a logged warning only, because those handlers are merely
  // unreachable. Ordering rule for adding a capability: Wing ships the handler
  // FIRST, the organ enables the opcode SECOND.
  app.get('/agent/v1/validate/opcodes', agentAuth('ro'), (_req, res) => {
    ok(res, {
      contract: CORTEX_CONTRACT_VERSION,
      registryHash: cortexRegistryHash(),
      opcodes: listOpcodes(),
    });
  });

  // ── S2: the ingestion half ─────────────────────────────────────────────────
  // Routes LIFTED from KEAP `server/agent.ts` (fs 744-777, embeddings 338-370,
  // objects 819-859, captures 887-912) and `server/intake.ts`. Shapes are
  // KEAP's, deliberately: one client feeds both daemons and one harness reads
  // both, so a drifted shape would surface in the nightly report as a corpus
  // difference that does not exist.

  /** KEAP's `/agent/v1/objects` cap. Kept identical so the harness's paging
   *  loop is the same loop against both sides — a larger page here would make
   *  the organ's read cheaper and the comparison asymmetric for no gain. */
  const MAX_LIMIT = 50;
  const trim = (s: string | undefined) => (s && s.length > 500 ? `${s.slice(0, 500)}…` : s);

  app.get('/agent/v1/fs/status', agentAuth('ro'), (_req, res) => ok(res, fsSyncStatus()));

  // rw, not ro: a pass WRITES the corpus (upserts, and — behind five guards —
  // prunes). The read-only token must not be able to reshape a knowledge base.
  app.post('/agent/v1/fs/sync', agentAuth('rw'), jsonBody, (_req, res) => {
    const roots = fsSyncStatus().userRoots;
    if (!roots.length) {
      return fail(res, 503, 'fs sync disabled: neither CORTEX_FS_USER_ROOTS nor KEAP_USER_FILES_DIR configured');
    }
    // The THROWING form on purpose (see `guardedSyncAllFs`): a caller that asked
    // for a pass and can be told "refused, and here is why" is told. Only the
    // unattended boot/interval callers swallow it. The 4-arg error handler at
    // the bottom turns the throw into a 500 in the standard envelope, with the
    // reason in the daemon log where the operator is.
    const r = syncAllFs();
    if (!r) return fail(res, 409, 'sync in progress');
    ok(res, { ...(r.users ?? {}), mappings: r.mappings });
  });

  app.get('/agent/v1/objects', agentAuth('ro'), (req, res) => {
    const type = req.query.type ? String(req.query.type) : undefined;
    const limit = Math.min(Number(req.query.limit) || 20, MAX_LIMIT);
    const offset = Math.max(Number(req.query.offset) || 0, 0);
    const items = db.getObjects('', true, type);
    ok(res, {
      total: items.length,
      results: items.slice(offset, offset + limit).map((o) => ({
        id: o.id,
        type: o.type,
        title: o.title,
        description: trim(o.description),
        resource: o.resource,
        tags: o.tags,
        userId: o.userId,
      })),
    });
  });

  app.get('/agent/v1/objects/:id', agentAuth('ro'), (req, res) => {
    const o = db.getObject(req.params.id);
    if (!o) return fail(res, 404, 'unknown object');
    // KEAP truncates the body at 8000 chars for its 16 KiB tool budget. The
    // truncation is REPRODUCED rather than lifted, because the harness hashes
    // this field: an organ that returned full bodies where KEAP returned
    // truncated ones would report every long card as a mismatch. `contentLink`
    // is dropped — it resolves against KEAP's content services, which this
    // organ does not have.
    ok(res, { ...o, body: o.body && o.body.length > 8000 ? `${o.body.slice(0, 8000)}\n…[truncated]` : o.body });
  });

  // ── GET /agent/v1/graph — the taxonomy id set, and why it had to exist ─────
  // LIFTED from KEAP `server/agent.ts:604-651`, node for node and filter for
  // filter, so one harness reads one shape off both daemons.
  //
  // It is here for ONE reason and it is a diff-harness reason. Until this route
  // existed, the taxonomy could only be compared on its COUNT (health's
  // `corpus.taxonomyNodes`) and on the onto1 digest — and the digest is not
  // available, because the running incumbent is KEAP 1.26.0 and does not publish
  // one. A count-only comparison passes two DIFFERENT 1841-node trees as
  // "PARITY", which is precisely the green a harness must not be able to earn:
  // §4.4 of the plan asks for taxonomy node ID SETS, and an id set needs a route
  // that lists ids. KEAP has had one all along; the organ was the missing half.
  //
  // Read-only and ro-scoped: `allNodes`, `getObjects`, `listRelations`,
  // `listRelationTypes`, `embeddingStats` — every one a SELECT. The harness's
  // access rule (§6.1, over /agent/v1 only, never a write) survives intact.
  //
  // The `edges`/`types` half comes with it rather than being trimmed away: a
  // route that answers at KEAP's path in a shape that is KEAP's minus two keys
  // is worse than no route, because a client reading `edges: []` cannot tell
  // "this organ does not serve relations" from "this corpus has none". The
  // organ's store carries both tables, so both are answered honestly.
  //
  // `relationEndpoint` is KEAP's both-endpoints-resolve guard (agent.ts:407-425),
  // reduced to the boolean this route uses: it exists so no edge dangles off a
  // retired node or a deleted object. KEAP's version also builds the classifier's
  // text, which nothing here consumes.
  type RelationKind = 'node' | 'object';
  const endpointResolves = (kind: RelationKind, id: string): boolean =>
    kind === 'node' ? Boolean(taxonomy.getNode(id)) : Boolean(db.getObject(id));

  app.get('/agent/v1/graph', agentAuth('ro'), (_req, res) => {
    const nodes: Array<{ id: string; kind: RelationKind; name: string; description?: string }> = [];
    for (const n of taxonomy.allNodes()) {
      nodes.push({ id: n.id, kind: 'node', name: n.name, description: trim(n.description) });
    }
    for (const o of db.getObjects('', true)) {
      nodes.push({
        id: `object:${o.id}`,
        kind: 'object',
        name: o.title,
        description: trim(o.description ?? o.body ?? undefined),
      });
    }
    const types = db.listRelationTypes().filter((t) => t.status === 'seed' || t.status === 'confirmed');
    const activeTypes = new Set(types.map((t) => t.type));
    const edges = db
      .listRelations({ status: 'confirmed' })
      .filter((r) => endpointResolves(r.fromKind, r.fromRef) && endpointResolves(r.toKind, r.toRef))
      .filter((r) => activeTypes.has(r.type))
      .map((r) => ({
        from: r.fromKind === 'object' ? `object:${r.fromRef}` : r.fromRef,
        to: r.toKind === 'object' ? `object:${r.toRef}` : r.toRef,
        fromKind: r.fromKind,
        toKind: r.toKind,
        type: r.type,
        confidence: r.confidence,
        justification: r.justification,
        source: r.source,
        model: r.model,
      }));
    ok(res, {
      nodes,
      edges,
      types,
      meta: { vectors: db.vectorSearchAvailable(), embeddings: db.embeddingStats() },
    });
  });

  app.get('/agent/v1/captures', agentAuth('ro'), (req, res) => {
    const limit = Math.min(Number(req.query.limit) || 20, MAX_LIMIT);
    const source = req.query.source ? String(req.query.source) : undefined;
    let items = db.getAllMetadataApi('', true);
    if (source) items = items.filter((c) => c.source === source);
    ok(res, {
      total: items.length,
      items: items.slice(0, limit).map((c) => ({
        id: c.id,
        title: c.title,
        description: trim(c.description),
        url: c.url,
        source: c.source,
        modality: c.modality,
        attribution: c.userId,
        metadata: c.metadata,
      })),
    });
  });

  // ── the embedding split, host side ─────────────────────────────────────────
  // The organ decides WHAT to embed (canonical text + content_hash diff); the
  // keap-embed-sync fan-out decides HOW (loopback Ollama) and pushes vectors
  // back. `model` and `dim` travel on the wire, which is what lets the fan-out
  // assert both targets declare the SAME pair before either pass runs (§4.3) —
  // one assertion converting a silent incomparability into a visible halt.
  app.get('/agent/v1/embeddings/pending', agentAuth('ro'), (req, res) => {
    if (!db.vectorSearchAvailable()) return fail(res, 503, 'vector layer unavailable');
    const limit = Math.min(Number(req.query.limit) || 100, 500);
    const { pending, total, pruned } = pendingEmbeddings(limit);
    ok(res, { model: EMBED_MODEL, dim: EMBED_DIM, total, pruned, items: pending });
  });

  app.post('/agent/v1/embeddings', agentAuth('rw'), jsonBody, (req, res) => {
    if (!db.vectorSearchAvailable()) return fail(res, 503, 'vector layer unavailable');
    const { model, dim, items } = req.body ?? {};
    if (!model || !Array.isArray(items) || !items.length) {
      return fail(res, 400, 'model + non-empty items required');
    }
    if (Number(dim) !== EMBED_DIM) return fail(res, 400, `dim must be ${EMBED_DIM}`);
    const rows: Array<{ kind: 'taxonomy' | 'capture' | 'note' | 'object'; refId: string; contentHash: string; vector: number[] }> = [];
    for (const it of items) {
      if (
        !['taxonomy', 'capture', 'note', 'object'].includes(it?.kind) ||
        typeof it?.refId !== 'string' ||
        typeof it?.contentHash !== 'string' ||
        !Array.isArray(it?.vector) ||
        it.vector.length !== EMBED_DIM
      ) {
        return fail(res, 400, `invalid item at index ${rows.length}`);
      }
      rows.push({ kind: it.kind, refId: it.refId, contentHash: it.contentHash, vector: it.vector });
    }
    // No `scheduleTopicRecluster()`: topics-mode is a KEAP UI concern and this
    // organ does not serve /topics. Declaring the trigger without the surface
    // would be the "declaring a contract you do not serve" mistake the health
    // handler's `contracts` block already refuses to make.
    ok(res, { upserted: db.upsertEmbeddings(String(model), EMBED_DIM, rows), submittedBy: `agent:${req.agentName}` });
  });

  // ── /ingest/v1 — the consolidator's target, capture-tier bearer ────────────
  // `jsonBody` is threaded in so it runs AFTER that bearer check, never before.
  //
  // No `markCorpusDirty()` wrapper around it, deliberately: `corpus_fts` is read
  // by exactly one thing, `search.ts::hybridSearch`, and this organ does not
  // serve semantic search. Marking an index dirty that nothing rebuilds and
  // nothing queries would be motion that looks like correctness. When the search
  // surface lands, the dirty flag lands with it.
  // The store epoch (S2): a DIGEST of db_identity, not the identity — this route
  // is pre-auth, so it publishes "am I still the same store" and nothing else.
  // The consolidator's ledger is a cache of what this store holds; without an
  // epoch a wiped store is never re-fed, because the source files are unchanged
  // and every signature still matches. Absent identity ⇒ absent field ⇒ the
  // feeder keeps its previous behaviour rather than resetting on every run.
  registerIngestRoutes(
    app,
    jsonBody,
    facts.dbIdentity?.id
      ? createHash('sha256').update(`cortex-store:${facts.dbIdentity.id}`).digest('hex').slice(0, 16)
      : undefined,
  );

  // Anything else is not this organ's. Answered in the same {success,error}
  // envelope so a caller that wandered over from KEAP's surface gets a fact
  // ("cortex does not serve this") rather than express's default HTML.
  app.use((req, res) =>
    fail(res, 404, `no such route on the cortex organ: ${req.method} ${req.path}`),
  );

  /**
   * The envelope of last resort — a FOUR-argument handler, which is the only
   * kind express dispatches errors to. The 404 above has two arguments and
   * therefore never sees one; without this, anything thrown or `next(err)`d
   * inside a handler falls through to express's finalhandler and comes back as
   * text/html — with `err.stack` inlined whenever NODE_ENV !== 'production',
   * which no deployment of this organ currently sets.
   *
   * Nothing about the error reaches the client except its status and, for the
   * 4xx that body-parser raises, its `type` (`entity.parse.failed`,
   * `entity.too.large`) — a stable, contentless token. The message and the stack
   * go to the log, where the operator is. A 5xx says only 'internal error':
   * anything more specific is a detail of an unexpected failure, and unexpected
   * failures are precisely the ones whose details were not vetted for disclosure.
   */
  app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
    const e = (err ?? {}) as { status?: unknown; statusCode?: unknown; type?: unknown };
    const claimed = typeof e.status === 'number' ? e.status : typeof e.statusCode === 'number' ? e.statusCode : 500;
    const status = Number.isInteger(claimed) && claimed >= 400 && claimed <= 599 ? claimed : 500;
    console.error(`[cortex] request error (${status})`, err);
    if (res.headersSent) return;
    const type = typeof e.type === 'string' ? e.type : null;
    fail(res, status, status >= 500 ? 'internal error' : `malformed request${type ? `: ${type}` : ''}`);
  });

  app.listen(PORT, HOST, () => {
    console.log(`[cortex] listening on http://${HOST}:${PORT}`);
    console.log(`[cortex] store            ${config.dbPath}`);
    console.log(`[cortex] db_identity      ${facts.dbIdentity?.id ?? '(none)'}`);
    console.log(`[cortex] ontologyVersion  ${facts.ontologyVersion}`);
    console.log(`[cortex] opcodeRegistry   ${cortexRegistryHash()} (contract ${CORTEX_CONTRACT_VERSION})`);
    console.log(
      `[cortex] agent surface    ${TOKEN_RO || TOKEN_RW ? 'enabled' : 'DISABLED — no token configured, /agent/v1/* answers 503'}`,
    );
    const roots = fsSyncStatus().userRoots;
    console.log(
      roots.length
        ? `[cortex] fs roots         ${roots.map((r) => `${r.spec}=${r.path}${r.exists ? '' : ' (ABSENT)'}`).join(', ')}`
        : '[cortex] fs roots         none configured — the corpus mirror is inert',
    );
    // AFTER listen: /health answers while the first walk runs, so a slow tree
    // never makes a live organ look dead. `startFsSync` swallows a refusal (the
    // mount sentinel) rather than taking the daemon down with it.
    startFsSync();
  });
}

main().catch((err) => {
  console.error('[cortex] fatal', err);
  process.exit(1);
});
