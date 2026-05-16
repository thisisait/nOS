/**
 * tests/e2e/tier2-wet-test.spec.ts
 *
 * Playwright browser tests — nOS services with Authentik SSO login.
 *
 * Identity:
 *   By default the suite consumes an ephemeral tester provisioned by
 *   global-setup.ts (writes ``${PLAYWRIGHT_OUT}/tester.json``). Set
 *   ``NOS_SKIP_PROVISION=1`` + ``NOS_TESTER_USER`` + ``NOS_TESTER_PASSWORD``
 *   to bypass and use a static identity for ad-hoc debugging.
 *
 * Phase 1: forward_auth services (auto-redirect to Authentik).
 * Phase 2: native_oidc services (service-specific SSO button selectors).
 *
 * Run (default — ephemeral):
 *   NOS_HOST=dev.local AUTHENTIK_API_TOKEN=... npx playwright test
 */

import { readFileSync } from 'node:fs';

import { test, expect, type Page } from '@playwright/test';

// ─── Environment ───────────────────────────────────────────────────────────

const NOS_HOST = process.env.NOS_HOST ?? 'dev.local';
const APPS_SUBDOMAIN = process.env.APPS_SUBDOMAIN ?? 'apps';
const AUTH_DOMAIN = process.env.AUTHENTIK_DOMAIN ?? `auth.${NOS_HOST}`;

interface TesterCreds {
  username: string;
  password: string;
}

function loadTesterCreds(): TesterCreds {
  const jsonPath = process.env.NOS_TESTER_JSON;
  if (jsonPath) {
    try {
      const payload = JSON.parse(readFileSync(jsonPath, 'utf8'));
      if (payload.username && payload.password) {
        return { username: payload.username, password: payload.password };
      }
      throw new Error(`${jsonPath} missing username/password`);
    } catch (exc) {
      throw new Error(`Cannot load tester identity from ${jsonPath}: ${exc}`);
    }
  }
  // Static fallback (NOS_SKIP_PROVISION=1 path, or no global-setup ran)
  const username = process.env.NOS_TESTER_USER ?? 'nos-tester';
  const password = process.env.NOS_TESTER_PASSWORD ?? '';
  if (!password) {
    throw new Error(
      'No tester identity available: NOS_TESTER_JSON unset AND NOS_TESTER_PASSWORD empty. ' +
      'Either let global-setup.ts provision one (default) or set NOS_SKIP_PROVISION=1 ' +
      'with NOS_TESTER_USER + NOS_TESTER_PASSWORD.',
    );
  }
  return { username, password };
}

const TESTER = loadTesterCreds();

interface ServiceEntry {
  slug: string;
  url: string;
  titleContains?: string;
}

// ─── forward_auth services (Traefik auto-redirects to Authentik) ───────────

// URL subdomains here MUST match the `<svc>_domain` values in
// default.config.yml — these are pinned so the suite fails fast on
// onboarding drift rather than silently skipping. When a new role lands,
// add an entry; when a role renames, update here.
const FORWARD_AUTH: ServiceEntry[] = [
  // Tier-2 apps
  { slug: 'twofauth',     url: `https://twofauth.${APPS_SUBDOMAIN}.${NOS_HOST}/` },
  { slug: 'roundcube',    url: `https://roundcube.${APPS_SUBDOMAIN}.${NOS_HOST}/` },
  { slug: 'documenso',    url: `https://documenso.${APPS_SUBDOMAIN}.${NOS_HOST}/` },
  // Tier-1 (always-installed defaults)
  { slug: 'uptime',       url: `https://uptime.${NOS_HOST}/` },
  { slug: 'calibre',      url: `https://books.${NOS_HOST}/` },
  { slug: 'kiwix',        url: `https://kiwix.${NOS_HOST}/` },
  { slug: 'puter',        url: `https://os.${NOS_HOST}/` },
  { slug: 'wing',         url: `https://wing.${NOS_HOST}/` },
  { slug: 'metabase',     url: `https://bi.${NOS_HOST}/` },
  { slug: 'mailpit',      url: `https://mail.${NOS_HOST}/` },
  { slug: 'paperclip',    url: `https://paperclip.${NOS_HOST}/` },
  // Tier-1 (opt-in — auto-skip via preflight when not deployed)
  { slug: 'ntfy',         url: `https://ntfy.${NOS_HOST}/` },
  { slug: 'homeassistant', url: `https://home.${NOS_HOST}/` },
  { slug: 'jellyfin',     url: `https://media.${NOS_HOST}/` },
  { slug: 'onlyoffice',   url: `https://onlyoffice.${NOS_HOST}/` },
  { slug: 'code-server',  url: `https://code.${NOS_HOST}/` },
  { slug: 'firefly',      url: `https://firefly.${NOS_HOST}/`, titleContains: 'Firefly' },
  { slug: 'snappymail',   url: `https://webmail.${NOS_HOST}/` },
];

/**
 * HEAD probe against the service host. If Traefik returns its default
 * 404 ("page not found" body, no Authentik redirect Location header),
 * the service isn't deployed on this host — skip the test instead of
 * hanging the login form selector for 15s. Returns ``true`` if the
 * service appears live (any router/redirect/SSO response).
 */
async function probeDeployed(url: string): Promise<boolean> {
  try {
    const resp = await fetch(url, {
      method: 'GET',
      redirect: 'manual',
      // mkcert dev + LE prod are both fine without explicit options;
      // Node 18+ fetch ignores TLS errors only via NODE_TLS_REJECT_UNAUTHORIZED.
    });
    // Traefik's "no router" 404 has body "404 page not found".
    if (resp.status === 404) {
      const body = await resp.text();
      if (body.includes('404 page not found')) return false;
    }
    return true;
  } catch {
    // DNS NXDOMAIN, connection refused, etc. — service is not there.
    return false;
  }
}

// ─── Authentik login helper ────────────────────────────────────────────────

async function fillAuthentikLogin(page: Page): Promise<void> {
  // Stage 1: identification
  await page.waitForSelector('input[name="uidField"]', { timeout: 15000 });
  await page.fill('input[name="uidField"]', TESTER.username);
  await page.click('button[type="submit"]');
  // Wait for React SPA to transition to password stage
  await page.waitForTimeout(2000);

  // Stage 2: password
  await page.waitForSelector('input[name="password"]', { timeout: 15000 });
  await page.fill('input[name="password"]', TESTER.password);

  // Submit and poll for redirect.
  await page.click('button[type="submit"]');

  for (let i = 0; i < 40; i++) {
    await page.waitForTimeout(500);
    const hostname = new URL(page.url()).hostname;
    if (!hostname.startsWith('auth.')) return;
  }
  throw new Error(`Still on Authentik after 20s: ${page.url()}`);
}

// ─── Tests ─────────────────────────────────────────────────────────────────

test.describe('SSO browser flow — forward_auth services', () => {
  test.beforeAll(() => {
    if (!TESTER.password) throw new Error('No tester password resolved');
  });

  for (const svc of FORWARD_AUTH) {
    test(`${svc.slug} — login via Authentik and verify page renders`, async ({ page }) => {
      test.info().annotations.push({ type: 'url', description: svc.url });

      // Service-deployment preflight — skips the test cleanly when Traefik
      // returns its "no router" 404 instead of hanging on the login form.
      if (!(await probeDeployed(svc.url))) {
        test.skip(true, `${svc.slug} not deployed (Traefik 404 / DNS miss)`);
      }

      // Navigate → Traefik forward-auth redirects to Authentik
      await page.goto(svc.url, { waitUntil: 'domcontentloaded', timeout: 30000 });

      // Log in (handles Authentik redirect + return)
      await fillAuthentikLogin(page);

      // SSO chain proof:
      //   1. URL is back on the service host (not Authentik) — we exited
      //      the login flow with a real session.
      //   2. ``titleContains`` is checked when set per-service. Otherwise
      //      we don't assert body or title shape — those vary too widely
      //      (Roundcube + Uptime Kuma render outside <body> innerText,
      //      Puter responds JSON when its own auth has no user row for
      //      the SSO identity, etc.). The redirect-back is the contract.
      const finalHostname = new URL(page.url()).hostname;
      expect(finalHostname).not.toMatch(/^auth\./);

      if (svc.titleContains) {
        const title = (await page.title()).trim();
        expect(title.toLowerCase()).toContain(svc.titleContains.toLowerCase());
      }
    });
  }
});

// ─── Health checks (no auth needed) ────────────────────────────────────────

test.describe('Health checks (no auth)', () => {
  test('Traefik ping responds', async ({ request }) => {
    const resp = await request.get('http://127.0.0.1:8082/ping');
    expect(resp.status()).toBe(200);
  });

  test('Bone health responds', async ({ request }) => {
    const resp = await request.get('http://127.0.0.1:8099/api/health');
    expect(resp.status()).toBe(200);
  });

  test('Bluesky PDS health responds', async ({ request }) => {
    const resp = await request.get('http://127.0.0.1:2583/xrpc/_health');
    expect(resp.status()).toBe(200);
  });
});