import { test, expect } from '@playwright/test';
import { loadCreds } from '../fixtures/credentials';

/**
 * Uptime Kuma first-run setup. Uses direct IP:port access (not the
 * Authentik-gated domain) because Uptime Kuma has no built-in SSO and
 * the setup wizard itself creates the first admin.
 *
 * Idempotent: if setup is done (login page instead of setup page), we pass.
 */
test('Uptime Kuma — first admin setup', async ({ page }) => {
  const creds = loadCreds('uptime_kuma');
  test.skip(!creds, 'Uptime Kuma credentials not set — skipping');

  await page.goto(creds!.url + '/setup', { waitUntil: 'domcontentloaded' });

  // Already past setup?
  const loginVisible = await page.getByLabel(/username/i).count();
  const setupHeader = await page.getByText(/create an admin|setup/i).count();
  if (loginVisible > 0 && setupHeader === 0) {
    test.info().annotations.push({ type: 'note', description: 'Uptime Kuma already provisioned' });
    return;
  }

  await page.getByLabel(/username/i).fill(creds!.username);
  await page.getByLabel(/^password/i).fill(creds!.password);
  await page.getByLabel(/confirm password|repeat password/i).fill(creds!.password);
  await page.getByRole('button', { name: /create|sign up/i }).first().click();

  await expect(page).toHaveURL(/\/(dashboard|$)/, { timeout: 15_000 });
});
