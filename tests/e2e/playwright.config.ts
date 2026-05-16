/**
 * tests/e2e/playwright.config.ts
 *
 * Playwright configuration for the nOS e2e SSO test suite.
 * Covers Tier-1 services (24) + Tier-2 apps (3) with browser-based
 * Authentik SSO login flow.
 *
 * Env vars:
 *   NOS_HOST                tenant_domain (default: dev.local)
 *   APPS_SUBDOMAIN          Tier-2 isolation segment (default: apps)
 *   NOS_TESTER_TIER         Tier for ephemeral identity (default: provider)
 *   NOS_SKIP_PROVISION      Set to "1" to use static NOS_TESTER_* env vars
 *                           instead of provisioning a fresh ephemeral tester
 *   NOS_TESTER_USER         Static fallback username (only with NOS_SKIP_PROVISION)
 *   NOS_TESTER_PASSWORD     Static fallback password (only with NOS_SKIP_PROVISION)
 *   AUTHENTIK_DOMAIN        Override auth domain (default: auth.<NOS_HOST>)
 *   AUTHENTIK_API_TOKEN     Admin token for ephemeral provisioning (REQUIRED)
 *   PLAYWRIGHT_WORKERS      Parallel workers (default: 1 — SSO is serial)
 *   PLAYWRIGHT_OUT          Output dir (default: ./.playwright-out)
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

  // A13.6 ephemeral SSO identity protocol — provisions a fresh
  // ``nos-tester-e2e-*`` user before the suite, revokes after.
  globalSetup: require.resolve('./global-setup.ts'),
  globalTeardown: require.resolve('./global-teardown.ts'),

  // Each SSO test: navigate → redirect → login form → password → redirect back.
  // Authentik can be slow on first hit (worker hydration). 90s per test is safe.
  timeout: 90_000,
  expect: { timeout: 10_000 },

  retries: 0,
  workers: Number(process.env.PLAYWRIGHT_WORKERS ?? 1),

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
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    userAgent:
      'Mozilla/5.0 (Macintosh; Apple Silicon Mac OS X 14_0) AppleWebKit/537.36 ' +
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 nOS-e2e/1.0',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});

export const ENV = {
  NOS_HOST,
  APPS_SUBDOMAIN,
  BASE_URL,
  OUT_DIR,
} as const;