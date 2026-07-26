/**
 * fs-sync CLI — LOCALLY AUTHORED (not a port). S2 step 2.
 *
 * One mirror pass over the configured host roots, plus the facts a reader needs
 * to check it, printed as a `CORTEX_FS_RESULT` JSON trailer.
 *
 *   npm run fs:sync            one pass, human summary + trailer
 *   npm run fs:sync -- --json  trailer only
 *
 * Two callers, and they are the reason this exists as a CLI rather than only as
 * an HTTP route:
 *
 *   - the fixture suite (`server/fs-sync.test.ts`), which needs a FRESH module
 *     graph per scenario: both `db.ts` (its data directory) and `fs-sync.ts`
 *     (its roots list) resolve their configuration at module LOAD, so "the same
 *     tree under a different roots config" is not expressible in one process.
 *   - the operator, who should be able to run the pass that is about to run
 *     unattended, against a copy of the store, before it is ever scheduled.
 *
 * ── Exit codes ──────────────────────────────────────────────────────────────
 *
 *   0  the pass ran (even if it scanned nothing and pruned nothing)
 *   1  the pass was REFUSED — the mount sentinel, or a store the organ does not
 *      own. Nothing was walked and nothing was pruned. Non-zero on purpose:
 *      §2.4.5's rule that a target's failure must be visible applies to the
 *      organ's own pass first.
 *   2  bad invocation
 *
 * A refusal prints NO trailer. That is deliberate — a `CORTEX_FS_RESULT` with
 * `scanned: 0` is exactly what an unmounted volume would look like to a reader
 * that only parsed the trailer, and this whole stage exists because those two
 * states must never be one value.
 */
import crypto from 'node:crypto';
import { openStore } from './cortex-store';
import { aliasFsEnv } from './cortex-fs';

const argv = process.argv.slice(2);
const JSON_ONLY = argv.includes('--json');
const log = JSON_ONLY ? () => {} : (l: string) => console.log(l);

async function main(): Promise<number> {
  const unknown = argv.filter((a) => a.startsWith('--') && a !== '--json');
  if (unknown.length) {
    console.error(`unknown flag(s) ${unknown.join(' ')} — expected --json`);
    return 2;
  }

  // Same order as the daemon: the store fixes KEAP_DATA_DIR, the alias fixes the
  // KEAP_FS_* names, and only THEN is `./fs-sync` imported (it reads its roots
  // at module load). A static import here would bind an empty roots list.
  const store = await openStore({ materialise: false, log });
  aliasFsEnv(process.env);
  const { syncAllFs, fsSyncStatus } = await import('./fs-sync');
  const { pendingEmbeddings } = await import('./embeddings');
  const db = store.db;

  const status = fsSyncStatus();
  const all = syncAllFs();
  const users = all?.users ?? null;

  // Everything a reader needs to check the pass, read off the STORE — never off
  // the pass's own return value. `cortex-store.ts::measureDocNodes` records the
  // reason at length: a count that agrees only with the process that produced it
  // is a claim about that process, not about the database.
  const objects = db.getObjects('', true)
    .filter((o) => o.frontmatter?.source === 'fs')
    .map((o) => ({
      id: o.id,
      userId: o.userId,
      type: o.type,
      title: o.title,
      visibility: o.visibility ?? 'private',
      size: o.frontmatter?.size as number | undefined,
      mtime: o.frontmatter?.mtime as number | undefined,
      degradedRead: o.frontmatter?.degradedRead as boolean | undefined,
      // The HASH, not the body: it is what catches the empty-body class and the
      // --facts-json divergence, both of which an id-only diff reads as green.
      bodyHash: o.body ? crypto.createHash('sha256').update(o.body).digest('hex') : null,
    }))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));

  let embeddingsPending = 0;
  try {
    embeddingsPending = pendingEmbeddings(0).total;
  } catch {
    embeddingsPending = -1; // no vector layer — distinct from "nothing pending"
  }

  if (!JSON_ONLY) {
    console.log('');
    console.log(`  roots            ${status.userRoots.length ? '' : '(none configured)'}`);
    for (const r of status.userRoots) {
      console.log(`    ${r.spec.padEnd(20)} ${r.path}${r.exists ? '' : '   ABSENT'}`);
    }
    if (users) {
      console.log(`  sentinel         ${users.sentinel ?? 'n/a'}`);
      console.log(`  scanned          ${users.scanned}  (${users.users.join(', ') || 'no uids'})`);
      console.log(`  upserted         ${users.upserted}`);
      console.log(`  unchanged        ${users.unchanged}`);
      console.log(`  removed          ${users.removed}`);
      if (users.pruneRefused) console.log('  prune            REFUSED — see the warnings above');
      if (users.rootsMissing?.length) console.log(`  roots missing    ${users.rootsMissing.join(', ')}`);
      if (users.emptyBodies) console.log(`  empty bodies     ${users.emptyBodies}`);
      if (users.rootCollisions) console.log(`  id collisions    ${users.rootCollisions}`);
      if (users.danglingAnchors) console.log(`  dangling anchors ${users.danglingAnchors}`);
      for (const p of users.perRoot ?? []) {
        console.log(`    root ${p.spec.padEnd(18)} scanned ${String(p.scanned).padStart(5)}  uids ${p.users.join(', ') || '-'}`);
      }
    } else {
      console.log('  users pass       not run (no roots configured)');
    }
    console.log(`  fs objects       ${objects.length} in store`);
    console.log(`  embed pending    ${embeddingsPending < 0 ? 'n/a (no vector layer)' : embeddingsPending}`);
    console.log('');
  }

  console.log('CORTEX_FS_RESULT ' + JSON.stringify({ users, objects, embeddingsPending, roots: status.userRoots }));
  return 0;
}

main().then(
  (code) => process.exit(code),
  (err) => {
    console.error(err instanceof Error ? err.message : String(err));
    process.exit(1);
  },
);
