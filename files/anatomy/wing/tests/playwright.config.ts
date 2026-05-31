import { defineConfig, devices } from '@playwright/test';
import * as dotenv from 'dotenv';
import * as path from 'path';

// Load ~/wing/.env (Ansible-generated) and tests/.env (opt-in overrides)
dotenv.config({ path: path.join(process.env.HOME || '', 'wing', '.env') });
dotenv.config({ path: path.join(__dirname, '.env'), override: true });

const baseURL = process.env.WING_URL || 'https://wing.dev.local';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
    ['json', { outputFile: 'playwright-report/results.json' }],
  ],

  use: {
    baseURL,
    ignoreHTTPSErrors: true,
    // SEC-6 edge-trust gate: browser requests to BasePresenter pages
    // (Homepage, /hub) are refused with 403 unless they carry the
    // X-Wing-Edge-Token header that Traefik's wing-edge@file middleware
    // injects. Mirror it here so browser-context navigations pass the
    // gate when hitting Wing directly (e.g. WING_URL=https://127.0.0.1:9000).
    // No-ops gracefully when WING_EDGE_TOKEN is unset — matching both the
    // suite's skip-when-unconfigured convention and the presenter's own
    // empty-token degradation path. API tests use request.newContext (a
    // fresh context that does not inherit this) and hit BaseApiPresenter,
    // which is exempt from the edge gate — so they are unaffected.
    extraHTTPHeaders: {
      'X-Wing-Edge-Token': process.env.WING_EDGE_TOKEN || '',
    },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },

  projects: [
    // Quick post-provision smoke checks (< 30s)
    {
      name: 'smoke',
      testMatch: /e2e\/smoke\/.*\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },

    // First-admin provisioning — idempotent UI-driven account creation
    // for services where ansible/API provisioning is not possible.
    {
      name: 'provisioning',
      testMatch: /e2e\/provisioning\/.*\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
