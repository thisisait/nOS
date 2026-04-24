import { test, expect } from '@playwright/test';
import { loadCreds } from '../fixtures/credentials';

/**
 * Jellyfin first-run wizard. Known-brittle on fresh DB init (upstream bug
 * makes the first run restart-loop until DB regenerates) — run this AFTER
 * the container stabilises.
 *
 * Idempotent: if wizard not shown (server already provisioned), passes.
 */
test('Jellyfin — first-run wizard', async ({ page }) => {
  const creds = loadCreds('jellyfin');
  test.skip(!creds, 'Jellyfin credentials not set — skipping');

  await page.goto(creds!.url + '/web/#/wizardstart.html', { waitUntil: 'domcontentloaded' });

  // If wizard done, we land on /web/index.html instead
  if (!/wizard/i.test(page.url())) {
    test.info().annotations.push({ type: 'note', description: 'Jellyfin already provisioned' });
    return;
  }

  // Step 1 — language
  await page.locator('#btnStartWizard, button:has-text("Next")').first().click().catch(() => {});

  // Step 2 — admin user
  await page.locator('#txtUsername').fill(creds!.username);
  await page.locator('#txtManualPassword').fill(creds!.password);
  await page.locator('#txtPasswordConfirm').fill(creds!.password);
  await page.locator('button[is="emby-button"]:has-text("Next")').first().click();

  // Step 3 — media libraries (skip by clicking Next)
  await page.locator('button:has-text("Next")').first().click({ timeout: 10_000 });

  // Step 4 — metadata language
  await page.locator('button:has-text("Next")').first().click({ timeout: 10_000 });

  // Step 5 — remote access (keep defaults, Next)
  await page.locator('button:has-text("Next")').first().click({ timeout: 10_000 });

  // Step 6 — finish
  await page.locator('button:has-text("Finish"), button:has-text("Done")').first().click({ timeout: 10_000 });

  await expect(page).toHaveURL(/\/web\/.*(login|index|home)/i, { timeout: 20_000 });
});
