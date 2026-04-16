import { type Page, expect } from '@playwright/test';

/**
 * Logs into Authentik SSO if the page redirects to auth.dev.local.
 * Idempotent — if already authenticated (session cookie present), does nothing.
 *
 * Required env:
 *   AUTHENTIK_USER (default: akadmin)
 *   AUTHENTIK_PASSWORD
 *
 * Returns true if login was performed, false if already authenticated.
 */
export async function loginAuthentik(page: Page): Promise<boolean> {
  const url = page.url();
  if (!url.includes('auth.') && !url.includes('/flows/')) {
    return false;
  }

  const username = process.env.AUTHENTIK_USER || 'akadmin';
  const password = process.env.AUTHENTIK_PASSWORD;
  if (!password) {
    throw new Error('AUTHENTIK_PASSWORD env var is required for SSO login');
  }

  // Authentik renders each stage as a LitElement-driven SPA. Poll up to
  // ~60s across identification + password stages by repeatedly probing
  // for a field/button and submitting once one is visible.

  const deadline = Date.now() + 60_000;
  let filledPassword = false;
  while (Date.now() < deadline) {
    // Final state — we've left auth flow
    const url = page.url();
    if (!url.includes('/flows/') && !url.includes('/outpost.goauthentik.io/') && !/\/\/auth\./.test(url)) {
      return true;
    }

    const pwField = page.getByRole('textbox', { name: /password/i });
    if (await pwField.first().isVisible().catch(() => false)) {
      await pwField.first().fill(password);
      await page.getByRole('button', { name: /continue|log in|sign in/i }).first().click();
      filledPassword = true;
      await page.waitForTimeout(500);
      continue;
    }

    const idField = page.getByRole('textbox', { name: /username|email/i });
    if (await idField.first().isVisible().catch(() => false)) {
      await idField.first().fill(username);
      await page.getByRole('button', { name: /continue|log in|sign in/i }).first().click();
      await page.waitForTimeout(500);
      continue;
    }

    // Some form of consent/TOTP/recovery that we don't know how to handle
    if (filledPassword) {
      const continueBtn = page.getByRole('button', { name: /continue|authorize|allow|skip/i });
      if (await continueBtn.first().isVisible().catch(() => false)) {
        await continueBtn.first().click();
        await page.waitForTimeout(500);
        continue;
      }
    }

    await page.waitForTimeout(500);
  }
  throw new Error('Authentik login timed out — stuck at ' + page.url());
}

/**
 * Navigates to a URL and handles Authentik SSO redirect if triggered.
 */
export async function gotoWithAuth(page: Page, targetUrl: string): Promise<void> {
  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
  // Authentik redirect lands on /flows/... or on auth.<domain>/
  if (page.url().includes('auth.') || page.url().includes('/flows/')) {
    await loginAuthentik(page);
  }
}
