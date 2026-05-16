/**
 * tests/e2e/global-teardown.ts
 *
 * Mirror of global-setup: deletes the ephemeral tester after the suite
 * finishes (pass or fail). Safe to invoke even if setup failed — checks
 * for the marker file before shelling out.
 *
 * If the JSON file carries ``_static: true`` we skip teardown (the operator
 * provided a static identity via NOS_SKIP_PROVISION=1 and we didn't create
 * it — touching it would be incorrect).
 *
 * Teardown is best-effort: failures are logged but never rethrown. Three
 * other safety nets exist for stranded testers:
 *   1. pytest atexit handler (different process, same scoping)
 *   2. files/anatomy/scripts/sweep-orphan-testers.py (operator CLI)
 *   3. future Pulse cron job (24h sweep)
 */

import { spawnSync } from 'node:child_process';
import { readFileSync, existsSync, unlinkSync } from 'node:fs';
import { join, resolve } from 'node:path';

const REPO_ROOT = resolve(__dirname, '..', '..');
const HELPER = join(REPO_ROOT, 'tools', 'e2e-auth-helper.py');

export default async function globalTeardown(): Promise<void> {
  const identityPath = process.env.NOS_TESTER_JSON;
  if (!identityPath || !existsSync(identityPath)) {
    console.log('[global-teardown] no tester.json — nothing to clean up');
    return;
  }

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(readFileSync(identityPath, 'utf8'));
  } catch (exc) {
    console.warn(`[global-teardown] cannot parse ${identityPath}: ${exc}`);
    return;
  }

  if (payload._static === true) {
    console.log('[global-teardown] static identity in use — skipping teardown');
    unlinkSync(identityPath);
    return;
  }

  if (!existsSync(HELPER)) {
    console.warn(`[global-teardown] helper missing at ${HELPER} — leaving tester for orphan-sweep`);
    return;
  }

  const username = (payload.username as string | undefined) ?? '<unknown>';
  console.log(`[global-teardown] revoking ephemeral tester ${username}…`);

  const result = spawnSync(
    'python3',
    [HELPER, 'teardown', '--input', identityPath],
    { stdio: ['ignore', 'inherit', 'inherit'], env: process.env },
  );

  if (result.status !== 0) {
    console.warn(
      `[global-teardown] helper exited ${result.status} — ` +
      `${username} may persist until orphan-sweep runs`,
    );
    return;
  }

  // Only delete the descriptor after successful teardown so a failed run
  // leaves operator a forensics breadcrumb.
  try {
    unlinkSync(identityPath);
  } catch {
    /* ignore */
  }
}
