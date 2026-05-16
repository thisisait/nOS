/**
 * tests/e2e/global-setup.ts
 *
 * Provisions a fresh ephemeral SSO tester before the Playwright suite runs.
 *
 * Doctrine (A13.6 — Vrstva A.5):
 *   - Static blueprint user ``nos-tester`` is a fallback for ad-hoc operator
 *     runs, NOT the default. Every CI run + every operator full-suite run
 *     gets a per-process tester whose username matches ``nos-tester-e2e-*``
 *     so orphan-sweep can find leftovers.
 *   - We shell out to ``tools/e2e-auth-helper.py provision`` rather than
 *     re-implementing the Authentik admin + Wing token mint in TypeScript —
 *     the Python lib already enforces three layers of safety against the
 *     A13.6 incident (cross-leak, superuser refusal, prefix check).
 *
 * Side effects:
 *   - Writes ``${PLAYWRIGHT_OUT}/tester.json`` with the full identity payload
 *     (username, password, user_pk, group_pk, token_*). Spec files read it.
 *   - Sets process.env.NOS_TESTER_JSON to that path so workers can find it.
 *
 * Opt-out:
 *   - ``NOS_SKIP_PROVISION=1`` skips provision and trusts that env vars
 *     ``NOS_TESTER_USER`` + ``NOS_TESTER_PASSWORD`` are already set (use this
 *     when running against a static identity for debugging).
 */

import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';

const REPO_ROOT = resolve(__dirname, '..', '..');
const HELPER = join(REPO_ROOT, 'tools', 'e2e-auth-helper.py');

export default async function globalSetup(): Promise<void> {
  const outDir = process.env.PLAYWRIGHT_OUT ?? join(__dirname, '.playwright-out');
  mkdirSync(outDir, { recursive: true });
  const identityPath = join(outDir, 'tester.json');

  // Always export the path; spec.ts reads NOS_TESTER_JSON.
  process.env.NOS_TESTER_JSON = identityPath;

  if (process.env.NOS_SKIP_PROVISION === '1') {
    console.log('[global-setup] NOS_SKIP_PROVISION=1 — using static identity from env');
    if (!process.env.NOS_TESTER_PASSWORD) {
      throw new Error(
        'NOS_SKIP_PROVISION=1 requires NOS_TESTER_PASSWORD to be set',
      );
    }
    // Write a stub so global-teardown knows not to invoke teardown.
    writeFileSync(identityPath, JSON.stringify({
      _static: true,
      username: process.env.NOS_TESTER_USER ?? 'nos-tester',
      password: process.env.NOS_TESTER_PASSWORD,
    }));
    return;
  }

  if (!existsSync(HELPER)) {
    throw new Error(`e2e-auth-helper.py not found at ${HELPER}`);
  }

  const tier = process.env.NOS_TESTER_TIER ?? 'provider';
  console.log(`[global-setup] provisioning ephemeral tester (tier=${tier})…`);

  const result = spawnSync(
    'python3',
    [HELPER, 'provision', '--tier', tier, '--output', identityPath],
    { stdio: ['ignore', 'inherit', 'inherit'], env: process.env },
  );

  if (result.status !== 0) {
    throw new Error(
      `e2e-auth-helper provision failed (exit ${result.status}); ` +
      'is Authentik reachable and AUTHENTIK_API_TOKEN set?',
    );
  }

  if (!existsSync(identityPath)) {
    throw new Error(`helper exited 0 but ${identityPath} does not exist`);
  }
  console.log(`[global-setup] wrote ${identityPath}`);
}
