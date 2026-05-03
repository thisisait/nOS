/**
 * tests/e2e/playwright.config.ts
 *
 * Playwright configuration for the nOS Tier-2 wet-test suite.
 *
 * Tier-1 environment knobs (env vars):
 *   NOS_HOST          tenant_domain (default: dev.local)
 *   APPS_SUBDOMAIN    Tier-2 isolation segment (default: apps)
 *   NOS_BASE_URL      override; if set, replaces https://${APPS_SUBDOMAIN}.${NOS_HOST}
 *   PLAYWRIGHT_OUT    output dir for results JSON / traces (default: ./.playwright-out)
 *
 * mkcert-trusted *.dev.local certs:
 *   The dev box has mkcert root in System keychain, so Chromium normally
 *   trusts them. We still set ignoreHTTPSErrors=true defensively so a
 *   freshly-cloned worktree (no keychain entry) doesn't redline every test.
 *   For LE-prod (Track G) this is moot — real certs.
 *
 * Reporter strategy:
 *   - 'list' for human runs (operator's terminal)
 *   - 'json' for Cowork-driven runs (parsable, fed back into Cowork queue)
 *   Both are always on; the JSON file lives at ${PLAYWRIGHT_OUT}/results.json.
 *
 * Workers:
 *   1 worker by default. Each pilot mutates server-side state (Authentik
 *   session cookies, Bone events, Kuma monitor cache) so parallel runs
 *   would race. CI can override with PLAYWRIGHT_WORKERS=N if isolated.
 */

import { defineConfig, devices } from '@playwright/test';
import * as path from 'path';

const NOS_HOST = process.env.NOS_HOST ?? 'dev.local';
const APPS_SUBDOMAIN = process.env.APPS_SUBDOMAIN ?? 'apps';
const BASE_URL =
  process.env.NOS_BASE_URL ?? `https://${APPS_SUBDOMAIN}.${NOS_HOST}`;
const OUT_DIR = process.env.PLAYWRIGHT_OUT ?? path.join(__dirname, '.playwright-out');

export default defineConfig({
  testDir: '.',
  testMatch: /.*\.spec\.ts$/,

  // Each test gets 30 s; the full file budget is 5 min. Authentik login
  // can be slow on first run while the worker hydrates the proxy session.
  timeout: 30_000,
  expect: { timeout: 5_000 },

  // No retries for now — wet-test failures should surface immediately so
  // the operator (or Cowork) can act on them. Flake-handling is post-H.
  retries: 0,
  workers: Number(process.env.PLAYWRIGHT_WORKERS ?? 1),

  // forbidOnly in CI prevents an accidental `.only` from skipping the rest.
  forbidOnly: Boolean(process.env.CI),

  reporter: [
    ['list'],
    ['json', { outputFile: path.join(OUT_DIR, 'results.json') }],
    ['html', { outputFolder: path.join(OUT_DIR, 'html'), open: 'never' }],
  ],
  outputDir: path.join(OUT_DIR, 'artifacts'),

  use: {
    baseURL: BASE_URL,
    ignoreHTTPSErrors: true,
    // Keep traces only on retry (we have retries=0, so effectively never).
    // Switch to 'on-first-retry' once Track P proper turns on retries.
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // Realistic UA so Authentik / Traefik don't 403 on us.
    userAgent:
      'Mozilla/5.0 (Macintosh; Apple Silicon Mac OS X 14_0) AppleWebKit/537.36 ' +
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 nOS-wet-test/0.1',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});

// Convenience export so spec files can import the same constants without
// re-deriving them — keeps env-var fallback logic in exactly one place.
export const ENV = {
  NOS_HOST,
  APPS_SUBDOMAIN,
  BASE_URL,
  OUT_DIR,
} as const;
