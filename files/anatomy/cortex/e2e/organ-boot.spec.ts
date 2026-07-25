import { test, expect, request as apiRequest } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

/**
 * LOCALLY AUTHORED (not a port) — the two boot properties KEAP's e2e cannot
 * express, because in KEAP they are not properties of a separate process.
 *
 *  A. FAIL CLOSED. No token configured ⇒ the whole `/agent/v1` surface answers
 *     503 "agent surface disabled", and presenting a token to a tokenless
 *     daemon does not authenticate anything. This needs a SECOND daemon with a
 *     different environment, which is why it is not in validate.spec.ts.
 *
 *  B. THE DAEMON OPENED THE STORE IT WAS CONFIGURED WITH. `server/db.ts:29-30`
 *     resolves its data directory at MODULE LOAD, and `openStore()` is what
 *     sets `KEAP_DATA_DIR`; `server/index.ts` therefore imports every cortex
 *     module dynamically, AFTER the store is open. esbuild preserves that
 *     laziness in the bundle (each module becomes an `__esm(...)` thunk) — but
 *     "preserves it today" is not a gate, and the failure mode is silent: the
 *     daemon would boot, mint an identity in `$PWD/data/keap.db`, answer every
 *     request plausibly, and report the configured path it never opened. So the
 *     assertion is made against the FILESYSTEM, not against the server's own
 *     account of itself.
 */

const ORIGIN_MAIN = 'http://127.0.0.1:18098';
const PORT_NOTOKEN = 18099;
const ORIGIN_NOTOKEN = `http://127.0.0.1:${PORT_NOTOKEN}`;
const STORE_MAIN = 'e2e/.data';
const STORE_NOTOKEN = 'e2e/.data-notoken';

test.describe.configure({ mode: 'serial' });

test.describe('organ boot', () => {
  test('B: the store on disk is the one /health reports, with the identity it reports', async ({
    request,
  }) => {
    const health = (await (await request.get('/health')).json()).data as {
      database: { id: string };
      store: { path: string };
    };

    // The daemon was told `CORTEX_STORE_PATH=e2e/.data` and the directory was
    // removed immediately before boot. If the dynamic-import ordering ever
    // broke, `db.ts` would bind whatever the ambient environment said and this
    // file would simply not be here.
    const dbFile = path.join(STORE_MAIN, 'keap.db');
    expect(fs.existsSync(dbFile), `${dbFile} must exist — the daemon opened some other file`).toBe(true);
    expect(fs.statSync(dbFile).size).toBeGreaterThan(0);
    expect(path.resolve(health.store.path)).toBe(path.resolve(dbFile));

    // `.cortex-store.json` is written by `assertOwnStore()` from the identity of
    // the database that was actually opened. Marker id === served id === this
    // directory is the closed loop: one store, one identity, one daemon.
    const marker = JSON.parse(fs.readFileSync(path.join(STORE_MAIN, '.cortex-store.json'), 'utf8')) as {
      organ: string;
      dbIdentity: string;
      dbFile: string;
    };
    expect(marker.organ).toBe('pazny.cortex');
    expect(marker.dbFile).toBe('keap.db');
    expect(marker.dbIdentity).toBe(health.database.id);
  });

  test('A: no token configured ⇒ 503 for the whole agent surface, and never an implicit identity', async () => {
    fs.rmSync(STORE_NOTOKEN, { recursive: true, force: true });

    // A deliberately hostile environment: no CORTEX_TOKEN_*, no
    // KEAP_AGENT_TOKEN_*, inherited or otherwise.
    const env = { ...process.env, PORT: String(PORT_NOTOKEN), CORTEX_STORE_PATH: STORE_NOTOKEN };
    delete env.CORTEX_TOKEN_RO;
    delete env.CORTEX_TOKEN_RW;
    delete env.KEAP_AGENT_TOKEN_RO;
    delete env.KEAP_AGENT_TOKEN_RW;

    let child: ChildProcess | null = null;
    let ctx: Awaited<ReturnType<typeof apiRequest.newContext>> | null = null;
    try {
      child = spawn(process.execPath, ['dist-server/index.js'], { env, stdio: 'pipe' });
      const died = new Promise<never>((_, reject) =>
        child!.once('exit', (code) => reject(new Error(`tokenless daemon exited ${code}`))),
      );

      ctx = await apiRequest.newContext({ baseURL: ORIGIN_NOTOKEN });
      await Promise.race([
        expect
          .poll(async () => (await ctx.get('/health').catch(() => null))?.status() ?? 0, { timeout: 60_000 })
          .toBe(200),
        died,
      ]);

      // The probe still answers. A liveness endpoint that 503s because nobody
      // configured a token would make a correctly fail-closed organ look dead,
      // which is backwards: it is up, and it is refusing on purpose.
      const health = (await (await ctx.get('/health')).json()).data as {
        status: string;
        surface: string;
        database: { id: string };
      };
      expect(health.status).toBe('OK');
      expect(health.surface).toBe('disabled');

      // Every agent route is 503, with or without a bearer. The 503 is checked
      // BEFORE the bearer is looked at, so a caller cannot distinguish "wrong
      // token" from "surface off" — and no request can acquire a scope the
      // operator never granted.
      const bodies = { source: '@input | classify(tax:01.01)' };
      for (const res of [
        await ctx.post('/agent/v1/validate', { data: bodies, headers: { 'Content-Type': 'application/json' } }),
        await ctx.post('/agent/v1/validate', {
          data: bodies,
          headers: { Authorization: 'Bearer e2e-ro', 'Content-Type': 'application/json' },
        }),
        await ctx.post('/agent/v1/validate', {
          data: bodies,
          headers: { Authorization: 'Bearer ', 'Content-Type': 'application/json' },
        }),
        await ctx.get('/agent/v1/validate/opcodes'),
        await ctx.get('/agent/v1/validate/opcodes', { headers: { Authorization: 'Bearer e2e-ro' } }),
      ]) {
        expect(res.status()).toBe(503);
        const json = (await res.json()) as { success: boolean; error: string };
        expect(json.success).toBe(false);
        expect(json.error).toContain('agent surface disabled');
      }

      // "503 for the WHOLE surface" has to survive a request that never reaches
      // a route handler. `express.json()` mounted app-wide runs in front of
      // agentAuth, and a body-parser SyntaxError skips every ordinary handler
      // for express's finalhandler — so an UNAUTHENTICATED caller sending a
      // truncated body to a daemon with NO tokens configured got 400 text/html
      // with a full stack trace, while a well-formed body on the same route got
      // the 503. The parser is mounted behind agentAuth now: the bearer check
      // is genuinely first, and nothing unauthorised is ever parsed.
      const malformed = await ctx.post('/agent/v1/validate', {
        headers: { 'Content-Type': 'application/json' },
        data: '{"source": ',
      });
      expect(malformed.status()).toBe(503);
      expect(malformed.headers()['content-type']).toContain('application/json');
      const malformedText = await malformed.text();
      expect(malformedText).not.toContain('SyntaxError');
      expect(malformedText).not.toContain('node_modules');
      expect((JSON.parse(malformedText) as { error: string }).error).toContain('agent surface disabled');

      // And it is its OWN store: two cortex daemons on one host mint two
      // identities and never share a file. The organ inherits no identity —
      // not KEAP's, not a sibling's (docs/specs/cortex-full-scope-decision.md,
      // "Two corrections").
      const mainCtx = await apiRequest.newContext({ baseURL: ORIGIN_MAIN });
      const mainHealth = (await (await mainCtx.get('/health')).json()).data as { database: { id: string } };
      await mainCtx.dispose();
      expect(health.database.id).not.toBe(mainHealth.database.id);
      expect(fs.existsSync(path.join(STORE_NOTOKEN, 'keap.db'))).toBe(true);
    } finally {
      await ctx?.dispose();
      child?.kill('SIGTERM');
      fs.rmSync(STORE_NOTOKEN, { recursive: true, force: true });
    }
  });

  test('nothing else is mounted: an unported KEAP path is a 404 in the envelope', async ({ request }) => {
    // The organ serves the cortex surface and stops there. A caller that wandered
    // over from KEAP's `/agent/v1` should get a fact, not express's default HTML
    // and not something that reads like a server fault.
    for (const p of ['/agent/v1/taxonomy/search?q=physics', '/agent/v1/objects', '/agent/v1/openapi.json', '/api/health']) {
      const res = await request.get(p, { headers: { Authorization: 'Bearer e2e-ro' } });
      expect(res.status(), p).toBe(404);
      const json = (await res.json()) as { success: boolean; error: string };
      expect(json.success).toBe(false);
      expect(json.error).toContain('no such route on the cortex organ');
    }
  });
});
