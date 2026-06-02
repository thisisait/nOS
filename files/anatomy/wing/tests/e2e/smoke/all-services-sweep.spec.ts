import { test, expect } from '@playwright/test';
import { loginAuthentik } from '../fixtures/authentik';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Per-service browser sweep (single SSO session).
 *
 * Walks every routed service (e2e/.services.json, generated from Traefik Host
 * rules), logging in to Authentik ONCE (the first redirect) so the shared
 * .pazny.eu session carries to every forward-auth service. Classifies each:
 *   OK   — reached the service (2xx/3xx, no gateway error)
 *   AUTH — stuck at the IdP after login (consent/MFA/redirect_uri issue)
 *   FAIL — 5xx / Bad Gateway (the dual-router 502 class)
 *   ERR  — navigation threw (timeout/TLS)
 * Writes e2e/.sweep-results.json. Hard-fails only on FAIL/ERR.
 *
 * Env: AUTHENTIK_USER (akadmin), AUTHENTIK_PASSWORD, DEV_DOMAIN=pazny.eu.
 */
const services: { name: string; url: string }[] = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', '.services.json'), 'utf-8'),
);

// raw SMTP host (no web UI) — would just time out
const SKIP = new Set(['smtp-stalwart']);
const AUTH_HOST = /\/\/auth\.pazny\.eu/;

test('per-service browser sweep (single SSO session)', async ({ page }) => {
  test.setTimeout(10 * 60_000);
  const results: any[] = [];

  for (const svc of services) {
    if (SKIP.has(svc.name)) {
      results.push({ name: svc.name, verdict: 'SKIP', detail: 'non-web (SMTP)' });
      console.log(`  [SKIP] ${svc.name}`);
      continue;
    }
    let verdict = 'OK', detail = '', status = 0, finalUrl = '';
    try {
      const resp = await page.goto(svc.url, { waitUntil: 'domcontentloaded', timeout: 25_000 });
      status = resp ? resp.status() : 0;

      if (/\/\/auth\.|\/flows\//.test(page.url())) {
        await loginAuthentik(page).catch(() => {});
        await page.waitForLoadState('domcontentloaded', { timeout: 15_000 }).catch(() => {});
        await page.waitForTimeout(800);
      }
      finalUrl = page.url();
      const body = ((await page.textContent('body').catch(() => '')) || '').slice(0, 1000);
      const title = (await page.title().catch(() => '')).slice(0, 40);

      const gateway = /502 Bad Gateway|Bad Gateway|504 Gateway|503 Service Unavailable/i.test(body)
        || [502, 503, 504].includes(status);

      if (gateway) {
        verdict = 'FAIL'; detail = `gateway ${status || ''} ${title}`.trim();
      } else if (svc.name === 'authentik') {
        verdict = 'OK'; detail = `IdP ${title}`;
      } else if (AUTH_HOST.test(finalUrl)) {
        verdict = 'AUTH'; detail = `stuck@IdP ${title}`;
      } else if (status >= 500) {
        verdict = 'FAIL'; detail = `http ${status} ${title}`;
      } else {
        verdict = 'OK'; detail = `${status} ${title}`;
      }
    } catch (e: any) {
      verdict = 'ERR';
      detail = String(e?.message || e).replace(/\s+/g, ' ').slice(0, 90);
    }
    results.push({ name: svc.name, verdict, status, finalUrl, detail });
    console.log(`  [${verdict.padEnd(4)}] ${svc.name.padEnd(18)} ${detail}`);
  }

  console.log('\n==== SWEEP SUMMARY ====');
  for (const v of ['OK', 'AUTH', 'SKIP', 'FAIL', 'ERR']) {
    const ns = results.filter((r) => r.verdict === v).map((r) => r.name);
    if (ns.length) console.log(`  ${v} (${ns.length}): ${ns.join(', ')}`);
  }
  fs.writeFileSync(path.join(__dirname, '..', '.sweep-results.json'), JSON.stringify(results, null, 2));

  const broken = results.filter((r) => r.verdict === 'FAIL' || r.verdict === 'ERR');
  expect(broken, `gateway/error failures:\n${JSON.stringify(broken, null, 2)}`).toHaveLength(0);
});
