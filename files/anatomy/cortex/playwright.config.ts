/**
 * E2E over the BUILT bundle (`npm run build` first) — build sequence step 8.
 *
 * Lifted in shape from KEAP's playwright.config.ts and reduced to what the organ
 * actually is: no SPA, no Traefik, no Authentik, no fs roots, no tenant domain.
 * The webServer command is the artifact a HOST would run — `node
 * dist-server/index.js` — not `tsx`. tsx stays a dev dependency and never boots
 * anything that is being asserted about.
 *
 * ── The store the suite boots against, and why it is NOT materialised ────────
 *
 * `rm -rf e2e/.data` then a plain boot ⇒ the organ mints a fresh identity and
 * `openStore()` materialises the SPINE ONLY: 790 nodes, 0 `taxonomy_nodes_ext`
 * rows, 16 seed verbs. That is deliberate, for two reasons:
 *
 *  1. It is the same input state KEAP's own e2e runs against (KEAP's config
 *     seeds an empty scratch schema plus a tiny self-model fixture; it does not
 *     ingest the canonical tree either). The ported assertions about late
 *     binding — `tax:node[Kinematics]` → `01.01.01.01`, `tax:node[motion]` →
 *     ambiguous — are therefore assertions about the SAME tree on both sides,
 *     rather than two different trees that happen to agree today.
 *  2. It is the state the pinned digest `onto1:76d1f3ad728b382b` is defined for,
 *     so `/health` and every `ast.binding` in this suite carry the literal the
 *     step-5 hard gate pins. A materialised store carries a different, larger
 *     digest — correct, but it would make the drift assertions here
 *     unfalsifiable against the gate.
 *
 * `CORTEX_TOKEN_RO`/`_RW` (not `KEAP_AGENT_TOKEN_*`) on purpose: that is the
 * organ's own deployment vocabulary and the alias in `server/index.ts` is the
 * only locally-authored code between the operator's variable and the verbatim
 * `server/tokens.ts` that compares it. Setting it here is what covers it.
 */
import { defineConfig } from '@playwright/test';

const PORT = 18098;
// 127.0.0.1, never `localhost`: the daemon binds the loopback ADDRESS, and on a
// dual-stack host `localhost` may resolve to ::1 first — which is a connection
// refused against a server that is up.
const ORIGIN = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  // One worker: the specs share one server and one store.
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  timeout: 30_000,
  use: {
    baseURL: ORIGIN,
    locale: 'en-US',
    trace: 'retain-on-failure',
  },
  // No `projects` and no browser device: this suite is HTTP only (the `request`
  // fixture). Declaring a chromium project would make `npx playwright install`
  // a prerequisite of a suite that never opens a page — a 300 MB download the
  // step-11 CI job would pay for nothing.
  webServer: {
    command:
      `rm -rf e2e/.data && ` +
      `PORT=${PORT} CORTEX_STORE_PATH=e2e/.data ` +
      `CORTEX_TOKEN_RO=e2e-ro CORTEX_TOKEN_RW=e2e-rw ` +
      `node dist-server/index.js`,
    // `url`, not `port`: playwright's port probe goes to localhost, and see the
    // ORIGIN note above.
    url: `${ORIGIN}/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
