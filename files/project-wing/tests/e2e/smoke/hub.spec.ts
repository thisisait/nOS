import { test, expect, request } from '@playwright/test';
import { gotoWithAuth } from '../fixtures/authentik';

test.describe('Glasswing Hub — smoke', () => {
  test('GET /api/v1/hub/systems returns systems list', async () => {
    const ctx = await request.newContext({ ignoreHTTPSErrors: true });
    const res = await ctx.get('/api/v1/hub/systems');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('systems');
    expect(body).toHaveProperty('stats');
    expect(Array.isArray(body.systems)).toBe(true);
    expect(body.systems.length).toBeGreaterThan(0);
    // Every system must have id + name
    for (const sys of body.systems) {
      expect(sys).toHaveProperty('id');
      expect(sys).toHaveProperty('name');
    }
    // Stats must include totals
    expect(body.stats.total).toBeGreaterThan(0);
    await ctx.dispose();
  });

  test('GET /api/v1/hub/health probes systems', async () => {
    const ctx = await request.newContext({ ignoreHTTPSErrors: true });
    const res = await ctx.get('/api/v1/hub/health');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('probes');
    expect(Array.isArray(body.probes)).toBe(true);
    for (const probe of body.probes) {
      expect(probe).toHaveProperty('id');
      expect(probe).toHaveProperty('status');
      expect(['up', 'down']).toContain(probe.status);
    }
    await ctx.dispose();
  });

  test('/hub renders systems grid after SSO login', async ({ page }) => {
    test.skip(!process.env.AUTHENTIK_PASSWORD, 'AUTHENTIK_PASSWORD not set');
    await gotoWithAuth(page, '/hub');
    await expect(page).toHaveURL(/\/hub$/);
    // At least one system card should render
    const cards = page.locator('.sys-card');
    await expect(cards.first()).toBeVisible();
    const count = await cards.count();
    expect(count).toBeGreaterThan(0);
    // Stack section headers should be visible
    const stacks = page.locator('.hub-stack-title');
    await expect(stacks.first()).toBeVisible();
  });

  test('public homepage loads without auth', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('h1')).toContainText('Glasswing');
    await expect(page.getByRole('link', { name: /systems hub/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /security dashboard/i })).toBeVisible();
  });
});
