import { beforeAll, afterAll, describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
// @ts-expect-error — plain ESM reference implementation, no types by design
import { composeFingerprint } from '../knowledge/onto1-compose.mjs';

/**
 * P-4 build-sequence step 5 — THE HARD GATE. Locally authored; NOT a KEAP port.
 *
 * `server/onto1-agreement.test.ts` (verbatim from KEAP, do not edit) proves the
 * two implementations agree *with each other*. That is a RELATIVE proof: if the
 * port had drifted the reference implementation and the runtime in the same
 * direction, it would still pass. This file supplies the missing ABSOLUTE half —
 * the literal `onto1:76d1f3ad728b382b` that KEAP's deployed validator stamps
 * into `ast.binding.ontologyVersion` — so a divergence is caught here rather
 * than in production, where it looks like every AST silently failing to bind.
 *
 * ── The digest is defined for ONE input state ───────────────────────────────
 *
 *   790 spine nodes  ·  ZERO taxonomy_nodes_ext rows  ·  16 SEED relation types
 *
 * A different state legitimately yields a different digest. A *materialised*
 * store carries 960 ext rows and hashes to something else entirely, and that is
 * not a regression — `cortex-store.test.ts` pins that distinction from the other
 * side. So the state is asserted FIRST and separately: a state failure must read
 * as "you are in the wrong state", never as "the port is broken".
 *
 * ── What this file does NOT cover, and why the fixtures are not redundant ────
 *
 * Measured on the real tree: every one of the 790 ids is ASCII, no node name
 * contains a non-ASCII character, and `localeCompare` happens to agree with
 * code-unit order on this exact id set. So §3.1 collation and §3.3's UTF-8
 * requirement are NOT discriminated at 790 nodes — an implementation that got
 * both wrong would still reproduce this digest. `knowledge/fixtures/onto1/`
 * (`case-05-verbs`, `case-06-unicode-and-tabs`) is what catches those, and the
 * conformance runner is therefore asserted here too rather than left to a
 * separate command. Neither gate substitutes for the other: the fixtures pin the
 * edge rules, the real tree pins the composed set at scale.
 *
 * Contract: docs/specs/onto1-composition-contract.md
 */

/** The one literal. 16 lowercase hex of sha256 over the canonical serialization. */
const PINNED = 'onto1:76d1f3ad728b382b';
/** The same bytes, full width — a digest prefix mismatch and a bytes mismatch are
 *  the same event, but this makes "the canonical string changed" legible on its own. */
const PINNED_SHA256 = '76d1f3ad728b382bb4c56659d92af06524ca23aab5ec6f19d90f23de3742c7de';

const SPINE_NODES = 790;
const LIVE_VERBS = 16;
const CANONICAL_LINES = SPINE_NODES + LIVE_VERBS; // 806
const CANONICAL_UTF8_BYTES = 29396;
const SPINE_DOMAINS = 12;

const ROOT = path.join(__dirname, '..');
const SPINE_DIR = path.join(ROOT, 'knowledge', 'spine');

function readSpine(): any[] {
  return fs
    .readdirSync(SPINE_DIR)
    .filter((f) => f.endsWith('.json') && f !== 'manifest.json')
    .sort()
    .map((f) => JSON.parse(fs.readFileSync(path.join(SPINE_DIR, f), 'utf8')));
}

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'cortex-onto1-digest-'));
process.env.KEAP_DATA_DIR = TMP;

let db: typeof import('./db');
let ontology: typeof import('./cortex-ontology-version');
let taxonomy: typeof import('./taxonomy');
let canonical: string;

beforeAll(async () => {
  db = await import('./db');
  await db.initDb();
  db.seedRelationTypes();
  ontology = await import('./cortex-ontology-version');
  taxonomy = await import('./taxonomy');
  canonical = ontology.canonicalOntologyVocabulary();
});

afterAll(() => fs.rmSync(TMP, { recursive: true, force: true }));

// Nothing in this file may mutate the tree or the verb table: every assertion
// below is a statement about the same one state established above.

describe('step 5 — the input state the pinned digest is defined for', () => {
  it('is 790 spine nodes from 12 domain documents', () => {
    expect(readSpine()).toHaveLength(SPINE_DOMAINS);
    expect(taxonomy.allNodes().length).toBe(SPINE_NODES);
  });

  it('has ZERO taxonomy_nodes_ext rows — no delta materialised', () => {
    const row = db.getDb().prepare('SELECT COUNT(*) AS n FROM taxonomy_nodes_ext').get() as { n: number };
    expect(row.n).toBe(0);
  });

  it('has exactly the 16 SEED relation types, none confirmed and none proposed', () => {
    const verbs = db.listRelationTypes();
    expect(verbs).toHaveLength(LIVE_VERBS);
    expect([...new Set(verbs.map((v) => v.status))]).toEqual(['seed']);
  });
});

describe('step 5 — the organ reproduces onto1:76d1f3ad728b382b over the real tree', () => {
  it('from the runtime (server/cortex-ontology-version.ts, via the in-memory tree)', () => {
    expect(ontology.cortexOntologyVersion()).toBe(PINNED);
  });

  it('from the reference implementation (knowledge/onto1-compose.mjs, from git)', () => {
    const ref = composeFingerprint(readSpine(), [], db.listRelationTypes());
    expect(ref.onto1).toBe(PINNED);
    expect(ref.nodeCount).toBe(SPINE_NODES);
    expect(ref.dropped).toEqual([]);
  });

  it('byte-identically — and names the first differing LINE when it does not', () => {
    const ref = composeFingerprint(readSpine(), [], db.listRelationTypes());
    // §6: "the canonical string is the diagnostic; the digest is the assertion."
    // Two digests that differ say nothing about WHICH field stopped mattering.
    const a = canonical.split('\n');
    const b = (ref.canonical as string).split('\n');
    const at = a.findIndex((line, i) => line !== b[i]);
    expect(at === -1 ? null : { line: at + 1, runtime: a[at], reference: b[at] }).toBeNull();
    expect(a).toHaveLength(b.length);
    expect(canonical).toBe(ref.canonical);
  });

  it('over exactly these bytes — 806 lines, 29396 UTF-8, no trailing newline', () => {
    expect(canonical.split('\n')).toHaveLength(CANONICAL_LINES);
    expect(Buffer.byteLength(canonical, 'utf8')).toBe(CANONICAL_UTF8_BYTES);
    expect(canonical.endsWith('\n')).toBe(false);
    expect(createHash('sha256').update(canonical, 'utf8').digest('hex')).toBe(PINNED_SHA256);
    expect(PINNED).toBe(`onto1:${PINNED_SHA256.slice(0, 16)}`);
  });
});

describe('step 5 — the record shape at real-tree scale (§3)', () => {
  it('is 790 node records then 16 verb records, all nodes before all verbs', () => {
    const lines = canonical.split('\n');
    const firstVerb = lines.findIndex((l) => l.startsWith('r\t'));
    expect(firstVerb).toBe(SPINE_NODES);
    expect(lines.slice(0, firstVerb).every((l) => l.startsWith('t\t'))).toBe(true);
    expect(lines.slice(firstVerb).every((l) => l.startsWith('r\t'))).toBe(true);
  });

  it('carries exactly four tab-separated fields per record — nothing leaked in', () => {
    // A port that appended zone/kind/path would still be "sorted and hashed", and
    // would differ from KEAP only in the digest. This says which shape is right.
    expect([...new Set(canonical.split('\n').map((l) => l.split('\t').length))]).toEqual([4]);
  });

  it('marks the 12 domain roots with the literal "-" sentinel (§3.1)', () => {
    const roots = canonical
      .split('\n')
      .filter((l) => l.startsWith('t\t') && l.split('\t')[2] === '-');
    expect(roots).toHaveLength(SPINE_DOMAINS);
    expect(roots[0]).toBe('t\t01\t-\tNatural Sciences');
    // and no node claims '' or 'null' as a parent instead
    expect(canonical).not.toContain('\tnull\t');
  });

  it('orders ids ascending by UTF-16 code unit (§3.1)', () => {
    const ids = canonical
      .split('\n')
      .filter((l) => l.startsWith('t\t'))
      .map((l) => l.split('\t')[1]);
    expect(ids).toEqual([...ids].sort((x, y) => (x < y ? -1 : x > y ? 1 : 0)));
  });

  it('excludes description and path (§3.3) — the named, accepted cost', () => {
    // 12 of the 790 seed nodes carry a description and 683 carry a ' > ' path.
    // Neither may appear anywhere in the serialization. Including description
    // would be "more correct" and would still be WRONG: it would disagree.
    const nodes = taxonomy.allNodes();
    const descs = nodes.filter((n) => n.description && n.description.length > 12);
    const paths = nodes.filter((n) => n.path && n.path.includes(' > '));
    expect(descs.length).toBeGreaterThan(0);
    expect(paths.length).toBeGreaterThan(0);
    expect(descs.filter((n) => canonical.includes(n.description!)).map((n) => n.id)).toEqual([]);
    expect(paths.filter((n) => canonical.includes(n.path)).map((n) => n.id)).toEqual([]);
  });
});

describe('step 5 — the digest is a function of its input, not a constant', () => {
  // Without this block every assertion above would still pass against an
  // implementation that returned the literal unconditionally. Run through the
  // PURE reference implementation so the runtime tree is never mutated.
  const base = () => composeFingerprint(readSpine(), [], db.listRelationTypes());
  const withSpine = (mutate: (docs: any[]) => void) => {
    const docs = JSON.parse(JSON.stringify(readSpine()));
    mutate(docs);
    return composeFingerprint(docs, [], db.listRelationTypes()).onto1;
  };

  it('moves when a grown row registers (§2)', () => {
    const grown = composeFingerprint(
      readSpine(),
      [{ id: 'nos', parentId: '', name: 'nOS' }],
      db.listRelationTypes(),
    );
    expect(grown.nodeCount).toBe(SPINE_NODES + 1);
    expect(grown.onto1).not.toBe(PINNED);
  });

  it('does NOT move when a row is dropped — the vocabulary is what registered (§2.5)', () => {
    const dropped = composeFingerprint(
      readSpine(),
      [{ id: 'orphan.child', parentId: 'orphan', name: 'Orphan' }],
      db.listRelationTypes(),
    );
    expect(dropped.dropped).toEqual(['orphan.child']);
    expect(dropped.nodeCount).toBe(SPINE_NODES);
    expect(dropped.onto1).toBe(PINNED);
  });

  it('moves on a rename and on a re-parent — both are resolution-affecting', () => {
    expect(withSpine((d) => { d[0].category.name += ' (renamed)'; })).not.toBe(PINNED);
    expect(withSpine((d) => {
      // graft domain 02's subtree under domain 01: same node set, new parentIds
      const sub = Object.values(d[1].category.subcategories ?? {})[0] as any;
      d[0].category.subcategories = { ...(d[0].category.subcategories ?? {}), grafted: sub };
      delete (d[1].category.subcategories as any)[Object.keys(d[1].category.subcategories)[0]];
    })).not.toBe(PINNED);
  });

  it('moves on a verb LABEL edit — resolveVerb matches against it (§3.2)', () => {
    const verbs = db.listRelationTypes().map((v, i) => (i === 0 ? { ...v, label: `${v.label} (edited)` } : v));
    expect(composeFingerprint(readSpine(), [], verbs).onto1).not.toBe(PINNED);
  });

  it('does NOT move when an agent plants a proposed verb (§3.2)', () => {
    const verbs = [
      ...db.listRelationTypes(),
      { type: 'planted-by-an-agent', status: 'proposed', label: 'planted' },
    ];
    const ref = composeFingerprint(readSpine(), [], verbs);
    expect(ref.onto1).toBe(PINNED);
    expect(ref.canonical).not.toContain('planted-by-an-agent');
  });

  it('is stable across calls — computed fresh, never memoised into a lie (§5)', () => {
    expect(base().onto1).toBe(PINNED);
    expect(ontology.cortexOntologyVersion()).toBe(PINNED);
  });
});

describe('step 5 — the fixture half of the gate', () => {
  it('passes all six onto1 conformance fixtures inside the organ', () => {
    // Run as a child process rather than re-implemented here: the runner IS the
    // artifact a port is graded against, and `npm test` must fail if it fails,
    // otherwise the edge rules the real tree cannot exercise ride on someone
    // remembering to type `npm run conformance`.
    const r = spawnSync(process.execPath, [path.join('knowledge', 'onto1-conformance.mjs')], {
      cwd: ROOT,
      encoding: 'utf8',
    });
    expect(r.stdout + r.stderr).toContain('onto1 conformance — 6/6');
    expect(r.status).toBe(0);
  });
});
