import { defineConfig, devices } from '@playwright/test';
import * as dotenv from 'dotenv';
import * as path from 'path';

// Load ~/glasswing/.env (Ansible-generated) and tests/.env (opt-in overrides)
dotenv.config({ path: path.join(process.env.HOME || '', 'glasswing', '.env') });
dotenv.config({ path: path.join(__dirname, '.env'), override: true });

const baseURL = process.env.GLASSWING_URL || 'https://glasswing.dev.local';

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
