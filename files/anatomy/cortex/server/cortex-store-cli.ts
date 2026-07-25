/**
 * Store CLI — LOCALLY AUTHORED (not a port).
 *
 * The operator/Ansible entry point for build-sequence steps 4 and 6. The daemon
 * (step 7) will call `openStore()` directly; this is the same code path with a
 * terminal on the end, so what CI and the operator exercise is what boots.
 *
 *   npm run store:init         open (or create) the store, no ingest
 *   npm run store:materialise  open + run the git ingest path + tune the ANN index
 *   npm run store:status       facts about the store as it stands, JSON trailer
 *
 * Flags: --force (re-apply every canonical file), --json (trailer only),
 *        --allow-spine-drift (do not fail when the generated spine is stale).
 */
import { openStore } from './cortex-store';

const argv = process.argv.slice(2);
const cmd = argv.find((a) => !a.startsWith('--')) ?? 'status';
const has = (f: string) => argv.includes(`--${f}`);
const JSON_ONLY = has('json');
const log = JSON_ONLY ? () => {} : (l: string) => console.log(l);

async function main(): Promise<number> {
  if (!['init', 'materialise', 'materialize', 'status'].includes(cmd)) {
    console.error(`unknown command ${JSON.stringify(cmd)} — expected init | materialise | status`);
    return 2;
  }

  const handle = await openStore({
    materialise: cmd === 'materialise' || cmd === 'materialize',
    force: has('force'),
    requireSpineInSync: !has('allow-spine-drift'),
    log,
  });

  const { facts, materialise, config } = handle;
  if (!JSON_ONLY) {
    console.log('');
    console.log(`  store            ${facts.dbPath}`);
    console.log(`  db_identity      ${facts.dbIdentity?.id ?? '(none)'}${facts.dbIdentity?.freshThisBoot ? '  [created this boot]' : ''}`);
    console.log(`  spine in sync    ${materialise.spineInSync}`);
    console.log(`  taxonomy nodes   ${facts.taxonomyNodes}  (fts rows ${facts.ftsRows})`);
    console.log(`  verbs            ${facts.verbs} total, ${facts.liveVerbs} live (seed|confirmed)`);
    console.log(`  relations        ${facts.toeRelations} toe, ${facts.curatedRelations} curated`);
    console.log(`  embeddings       ${facts.embeddings}`);
    console.log(`  vector layer     ${facts.vectorSearchAvailable ? 'available' : 'UNAVAILABLE (FTS-only)'}`);
    console.log(`  ann index        ${facts.ann.outcome} — ${facts.ann.indexExpr ?? '(none)'}`);
    if (facts.ann.shadowBytes != null) {
      console.log(`  ann shadow       ${(facts.ann.shadowBytes / 1048576).toFixed(1)} MB`);
    }
    if (facts.ann.error) console.log(`  ann error        ${facts.ann.error}`);
    console.log(`  ontologyVersion  ${facts.ontologyVersion}`);
    console.log('');
  }

  console.log('CORTEX_STORE_RESULT ' + JSON.stringify({ command: cmd, config: { storeDir: config.storeDir, ann: config.ann }, materialise, facts }));
  return facts.ann.outcome === 'rejected-no-index' ? 1 : 0;
}

main().then(
  (code) => process.exit(code),
  (err) => {
    console.error(err instanceof Error ? err.message : String(err));
    process.exit(1);
  },
);
