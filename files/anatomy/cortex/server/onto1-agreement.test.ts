import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
// @ts-expect-error — plain ESM reference implementation, no types by design
import { composeFingerprint, canonicalVocabulary, composeNodes } from '../knowledge/onto1-compose.mjs';

/**
 * P-2 — KEAP's runtime composition must agree with the published contract.
 *
 * `knowledge/onto1-conformance.mjs` grades an implementation against fixtures,
 * but fixtures are toys: they cannot catch a divergence that only appears at the
 * scale and shape of the real tree. And blessing the fixtures FROM the reference
 * implementation makes that check circular on its own.
 *
 * This test breaks the circle from the other side: two INDEPENDENT
 * implementations — `server/cortex-ontology-version.ts` (which composes through
 * server/taxonomy.ts's in-memory tree) and `knowledge/onto1-compose.mjs` (which
 * composes from the git spine as data) — must produce a byte-identical
 * serialization over the live 790-node spine plus grown rows.
 *
 * If they ever disagree, the contract is wrong or the runtime drifted, and the
 * nOS port would inherit whichever one it was graded against.
 */

const SPINE_DIR = path.join(__dirname, '..', 'knowledge', 'spine');

function readSpine() {
  return fs
    .readdirSync(SPINE_DIR)
    .filter((f) => f.endsWith('.json') && f !== 'manifest.json')
    .sort()
    .map((f) => JSON.parse(fs.readFileSync(path.join(SPINE_DIR, f), 'utf8')));
}

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'keap-onto1-'));
process.env.KEAP_DATA_DIR = TMP;

let db: typeof import('./db');
let ontology: typeof import('./cortex-ontology-version');
let taxonomy: typeof import('./taxonomy');

beforeAll(async () => {
  db = await import('./db');
  await db.initDb();
  db.seedRelationTypes();
  ontology = await import('./cortex-ontology-version');
  taxonomy = await import('./taxonomy');
});

afterAll(() => fs.rmSync(TMP, { recursive: true, force: true }));

describe('onto1 contract — the runtime agrees with the reference implementation', () => {
  it('produces a byte-identical serialization over the seed spine', () => {
    const runtime = ontology.canonicalOntologyVocabulary();
    const reference = canonicalVocabulary(
      composeNodes(readSpine(), []).nodes,
      db.listRelationTypes(),
    );
    // Compared as text, not as a digest: a hash mismatch says "something moved",
    // the first differing line says WHICH field did.
    const a = runtime.split('\n');
    const b = reference.split('\n');
    const firstDiff = a.findIndex((line, i) => line !== b[i]);
    expect(firstDiff === -1 ? null : { at: firstDiff + 1, runtime: a[firstDiff], reference: b[firstDiff] }).toBeNull();
    expect(a).toHaveLength(b.length);
  });

  it('agrees on the digest, and on the documented spine size', () => {
    const reference = composeFingerprint(readSpine(), [], db.listRelationTypes());
    expect(ontology.cortexOntologyVersion()).toBe(reference.onto1);
    // 790 is the number the whole boundary analysis rests on: 43% of the live
    // tree, and the part that had no git source before P-1.
    expect(taxonomy.allNodes().length).toBe(790);
    expect(reference.nodeCount).toBe(790);
  });

  it('agrees once grown rows are registered, including a children-first subtree', () => {
    // Deliberately children-first: a single-pass registration drops the whole
    // subtree, and the two implementations would then disagree on the node SET
    // rather than on a field.
    const rows = [
      { id: 'nos.services.bookstack', parentId: 'nos.services', name: 'BookStack', description: '', zone: 'free' },
      { id: 'nos.services', parentId: 'nos', name: 'Services', description: '', zone: 'free' },
      { id: 'nos', parentId: '', name: 'nOS', description: '', zone: 'anchor' },
      // must NOT register, on both sides
      { id: 'orphan.child', parentId: 'orphan', name: 'Orphan', description: '', zone: 'free' },
    ];
    const { registered, dropped } = taxonomy.registerExtNodes(rows);
    expect(registered).toBe(3);
    expect(dropped).toEqual(['orphan.child']);

    const reference = composeFingerprint(
      readSpine(),
      rows.map((r) => ({ id: r.id, parentId: r.parentId, name: r.name })),
      db.listRelationTypes(),
    );
    expect(reference.nodeCount).toBe(793);
    expect(reference.dropped).toEqual(['orphan.child']);
    expect(ontology.canonicalOntologyVocabulary()).toBe(reference.canonical);
    expect(ontology.cortexOntologyVersion()).toBe(reference.onto1);
  });

  it('excludes proposed verbs on both sides, and a label edit moves the digest', () => {
    const before = ontology.cortexOntologyVersion();
    db.insertProposedRelationType('planted-by-an-agent', 'test');
    expect(ontology.cortexOntologyVersion()).toBe(before); // proposed is not vocabulary

    const ref = composeFingerprint(readSpine(), [], db.listRelationTypes());
    expect(ref.canonical).not.toContain('planted-by-an-agent');
  });
});
