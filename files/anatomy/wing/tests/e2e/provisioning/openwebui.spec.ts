import { test, expect } from '@playwright/test';
import { loadCreds } from '../fixtures/credentials';
import { loginAuthentik } from '../fixtures/authentik';

/**
 * Open WebUI onboarding — pure-SSO (2026-05-29).
 *
 * Public local signup is CLOSED (ENABLE_SIGNUP=false): the old "first visitor
 * to sign up becomes admin" race is gone. Access is via Authentik OIDC, and a
 * tier-1 (nos-admins / nos-providers) Authentik user auto-becomes a WebUI admin
 * via OAUTH role management (OAUTH_ADMIN_ROLES). The admin is also DB-seeded by
 * the playbook (break-glass), so the instance is fully provisioned on a blank.
 */

test('Open WebUI — public local signup is closed', async ({ page }) => {
  const creds = loadCreds('openwebui');
  test.skip(!creds, 'Open WebUI credentials not set — skipping');

  await page.goto(creds!.url + '/auth', { waitUntil: 'domcontentloaded' });

  // The public "Sign up" toggle must be GONE — that was the first-admin race.
  await expect(page.getByRole('button', { name: /sign up/i })).toHaveCount(0);

  // Authentik SSO must be the access path (pure-SSO onboarding).
  const sso = page.getByRole('button', { name: /authentik|continue with|sign in with/i });
  await expect(sso.first()).toBeVisible({ timeout: 10_000 });
});

test('Open WebUI — Authentik admin gets admin role via OIDC groups', async ({ page }) => {
  const creds = loadCreds('openwebui');
  test.skip(!creds, 'Open WebUI credentials not set — skipping');
  test.skip(
    !process.env.AUTHENTIK_PASSWORD,
    'AUTHENTIK_PASSWORD not set — skipping SSO admin-grant check (set AUTHENTIK_USER to a nos-admins member)',
  );

  await page.goto(creds!.url + '/auth', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /authentik|continue with|sign in with/i }).first().click();
  await loginAuthentik(page);

  // Back in Open WebUI (chat UI), not bounced to a "pending approval" screen.
  await expect(page).not.toHaveURL(/\/auth/i, { timeout: 20_000 });

  // Admin grant: the admin-only users surface must be reachable. A non-admin
  // OIDC user (allowed but not in OAUTH_ADMIN_ROLES) is bounced off /admin.
  await page.goto(creds!.url + '/admin/users', { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveURL(/\/admin/i, { timeout: 15_000 });
});
