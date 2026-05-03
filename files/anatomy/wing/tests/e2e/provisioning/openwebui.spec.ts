import { test, expect } from '@playwright/test';
import { loadCreds } from '../fixtures/credentials';

/**
 * Open WebUI first-signup (becomes the admin). No API for this flow —
 * the first person to sign up is promoted to admin automatically.
 *
 * Idempotent: if signup is disabled (admin already exists), we skip.
 */
test('Open WebUI — first admin signup', async ({ page }) => {
  const creds = loadCreds('openwebui');
  test.skip(!creds, 'Open WebUI credentials not set — skipping');

  await page.goto(creds!.url + '/auth', { waitUntil: 'domcontentloaded' });

  // The signup form shows a "Sign up" toggle when no admin exists yet.
  // After the admin is created, only the login form is visible.
  const signupToggle = page.getByRole('button', { name: /sign up/i });
  const hasSignup = await signupToggle.count();
  if (hasSignup === 0) {
    test.info().annotations.push({ type: 'note', description: 'Open WebUI already has admin' });
    return;
  }
  await signupToggle.first().click().catch(() => {});

  // Fill the form
  await page.getByPlaceholder(/name/i).first().fill('Admin');
  await page.getByPlaceholder(/email/i).first().fill(creds!.email || creds!.username);
  await page.getByPlaceholder(/password/i).first().fill(creds!.password);

  await page.getByRole('button', { name: /create account|sign up/i }).first().click();

  // Successful signup redirects to / (chat UI)
  await expect(page).toHaveURL(/\/(c|$)/i, { timeout: 15_000 });
});
