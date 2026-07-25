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
 * and NOTHING else. Every other `/agent/v1/*` path KEAP serves — taxonomy,
 * search, objects, relations, tables, fs, lint, captures, curator, topics,
 * embeddings, openapi.json — and the whole `/api` + SPA surface stay in KEAP.
 * The 404 handler at the bottom says so in the envelope rather than letting an
 * unmounted path fall through to something that looks like a server error.
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
  const { TOKEN_RO, TOKEN_RW, tokenEquals } = await import('./tokens');
  const { CORTEX_CONTRACT_VERSION, cortexRegistryHash, listOpcodes } = await import('./cortex-opcodes');
  const { cortexOntologyVersion } = await import('./cortex-ontology-version');
  const { validateCortex } = await import('./cortex-validate');
  const { cortexValidateRequestSchema } = await import('../shared/contracts/cortex');
  const { buildVersion } = await import('./build-version');

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
  app.use(express.json({ limit: '2mb' }));

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
  app.post('/agent/v1/validate', agentAuth('ro'), (req, res) => {
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

  // Anything else is not this organ's. Answered in the same {success,error}
  // envelope so a caller that wandered over from KEAP's surface gets a fact
  // ("cortex does not serve this") rather than express's default HTML.
  app.use((req, res) =>
    fail(res, 404, `no such route on the cortex organ: ${req.method} ${req.path}`),
  );

  app.listen(PORT, HOST, () => {
    console.log(`[cortex] listening on http://${HOST}:${PORT}`);
    console.log(`[cortex] store            ${config.dbPath}`);
    console.log(`[cortex] db_identity      ${facts.dbIdentity?.id ?? '(none)'}`);
    console.log(`[cortex] ontologyVersion  ${facts.ontologyVersion}`);
    console.log(`[cortex] opcodeRegistry   ${cortexRegistryHash()} (contract ${CORTEX_CONTRACT_VERSION})`);
    console.log(
      `[cortex] agent surface    ${TOKEN_RO || TOKEN_RW ? 'enabled' : 'DISABLED — no token configured, /agent/v1/* answers 503'}`,
    );
  });
}

main().catch((err) => {
  console.error('[cortex] fatal', err);
  process.exit(1);
});
