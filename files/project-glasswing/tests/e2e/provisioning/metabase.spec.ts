import { test, expect } from '@playwright/test';
import { loadCreds } from '../fixtures/credentials';

/**
 * Metabase first-admin provisioning.
 *
 * Metabase's setup wizard uses a one-time setup-token obtained from the DB
 * table `setting` (key `setup-token`). Ansible doesn't currently provision
 * admin via API, so we drive the wizard via UI.
 *
 * Idempotent: if the first page is already the login screen (setup done),
 * the test passes without doing anything.
 */
test('Metabase — create first admin via setup wizard', async ({ page }) => {
  const creds = loadCreds('metabase');
  test.skip(!creds, 'Metabase credentials not set — skipping');

  await page.goto(creds!.url + '/setup', { waitUntil: 'domcontentloaded' });

  // If already past setup, we land on /auth/login or /
  if (!/\/setup/.test(page.url())) {
    test.info().annotations.push({ type: 'note', description: 'Metabase already provisioned — nothing to do' });
    return;
  }

  // Step 1: language (pick English and continue)
  await page.getByRole('radio', { name: /english/i }).first().check({ force: true }).catch(() => {});
  await page.getByRole('button', { name: /next|continue/i }).first().click();

  // Step 2: first admin user
  await page.getByLabel(/first name/i).fill('Admin');
  await page.getByLabel(/last name/i).fill('User');
  await page.getByLabel(/email/i).fill(creds!.email || creds!.username);
  await page.getByLabel(/company/i).fill('nOS').catch(() => {});
  await page.getByLabel(/^password/i).fill(creds!.password);
  await page.getByLabel(/confirm password/i).fill(creds!.password);
  await page.getByRole('button', { name: /next|continue/i }).click();

  // Step 3: skip sample database
  await page.getByRole('button', { name: /i'll add my data later|skip/i }).click().catch(() => {});

  // Step 4: data preferences — decline telemetry
  await page.getByRole('radio', { name: /no, don'?t allow/i }).check({ force: true }).catch(() => {});
  await page.getByRole('button', { name: /finish|take me to/i }).click();

  // Verify landing page
  await expect(page).toHaveURL(/\/(collection|dashboard|browse|$)/, { timeout: 15_000 });
});
