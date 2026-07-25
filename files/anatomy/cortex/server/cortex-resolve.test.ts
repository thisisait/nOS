import { beforeAll, afterAll, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

/**
 * Cortex phase 4 — operand resolution, the identity model (D1), late binding and
 * the AST binding stamp, exercised against a real throwaway libSQL DB.
 *
 * The pure half (tokenizer, parser, structural phase, registry) is covered by
 * server/cortex-lang.test.ts with no database at all. Everything here needs one,
 * so KEAP_DATA_DIR is set BEFORE `await import('./db')` — the data dir is
 * resolved at module load, and a static top-level `import * as db` would bind
 * the wrong database (the lesson server/relations.test.ts:13 records).
 *
 * The spec's numbered test vectors (docs/specs/cortex-validate.md §8) are cited
 * per test as `vector N`.
 */
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'keap-cortex-'));
process.env.KEAP_DATA_DIR = TMP;

let db: typeof import('./db');
let taxonomy: typeof import('./taxonomy');
let lang: typeof import('./cortex-lang');
let opcodes: typeof import('./cortex-opcodes');
let ontologyVersion: typeof import('./cortex-ontology-version');
let resolve: typeof import('./cortex-resolve');
let cortex: typeof import('./cortex-validate');

beforeAll(async () => {
  db = await import('./db');
  await db.initDb();
  // The boot steps this suite depends on (server/index.ts:45-56), called
  // explicitly because there is no server here.
  db.seedRelationTypes();
  taxonomy = await import('./taxonomy');
  db.rebuildTaxonomyFts(taxonomy.allNodes());
  lang = await import('./cortex-lang');
  opcodes = await import('./cortex-opcodes');
  ontologyVersion = await import('./cortex-ontology-version');
  resolve = await import('./cortex-resolve');
  cortex = await import('./cortex-validate');
});

afterAll(() => {
  fs.rmSync(TMP, { recursive: true, force: true });
});

// --- helpers ---------------------------------------------------------------

const run = (source: string, ttl?: number) => cortex.validateCortex(source, ttl);

const firstOperand = (report: ReturnType<typeof run>) => {
  expect(report.ast).not.toBeNull();
  return report.ast!.pipeline.stages[0].operands[0];
};

const codes = (report: ReturnType<typeof run>) => report.errors.map((e) => e.code);
const warnCodes = (report: ReturnType<typeof run>) => report.warnings.map((w) => w.code);

// ---------------------------------------------------------------------------
// tax: — exact binding
// ---------------------------------------------------------------------------

describe('tax: exact resolution', () => {
  it('vector 1 — resolves a seed id, stamps id + name-at-resolution, no diagnostics', () => {
    const report = run('@input | classify(tax:01.01)');
    expect(report.valid).toBe(true);
    expect(report.complete).toBe(true);
    expect(report.phase).toBe(1);
    expect(report.errors).toEqual([]);
    expect(report.warnings).toEqual([]);

    const stage = report.ast!.pipeline.stages[0];
    expect(stage.opcode).toBe('classify');
    expect(stage.mutating).toBe(false);
    expect(stage.effective).toEqual({});
    expect(firstOperand(report)).toMatchObject({
      ns: 'tax',
      kind: 'resolved',
      binding: 'exact',
      scopeHint: null,
      surface: '01.01',
      id: '01.01',
      resolvedName: 'Physics',
    });
  });

  it('resolves a GROWN (ext) node through the same oracle as a seed node', () => {
    taxonomy.registerExtNodes([
      { id: 'cxfix', parentId: '', name: 'Cortex Fixture Root', description: '', zone: 'anchor' },
    ]);
    const operand = firstOperand(run('@input | classify(tax:cxfix)'));
    expect(operand.kind).toBe('resolved');
    expect(operand.resolvedName).toBe('Cortex Fixture Root');
  });

  it('vector 5/18 (uniformity) — an absent id and a DROPPED ext row are byte-identical', () => {
    // `registerExtNodes` deliberately drops a row whose parent never resolves.
    // The row would exist on disk; `getNode` is the only oracle, so it must NOT
    // resolve — and it must be indistinguishable from an id that never existed.
    const { dropped } = taxonomy.registerExtNodes([
      { id: 'orphan.dropped', parentId: 'no-such-parent', name: 'Orphan', description: '', zone: 'free' },
    ]);
    expect(dropped).toEqual(['orphan.dropped']);

    // Same LENGTH on purpose: `offset`/`length` describe the caller's own text,
    // which the caller obviously already knows, so the invariant is byte
    // identity after substituting `detail.surface` — not after erasing the span.
    const droppedReport = run('@input | classify(tax:orphan.dropped)');
    const absentReport = run('@input | classify(tax:phantom.absent)');
    expect(droppedReport.valid).toBe(false);
    expect(droppedReport.ast).toBeNull();
    expect(codes(droppedReport)).toEqual(['unknown_operand']);

    const normalize = (r: ReturnType<typeof run>) =>
      JSON.stringify(r.errors).split('orphan.dropped').join('X').split('phantom.absent').join('X');
    expect(normalize(droppedReport)).toBe(normalize(absentReport));
    expect(droppedReport.errors[0].detail).toEqual({ ns: 'tax', surface: 'orphan.dropped' });
  });

  it('vector 17 — a shape-illegal id never reaches the resolver', () => {
    const report = run('@input | classify(tax:Nos.Services)');
    expect(codes(report)).toEqual(['malformed_operand']);
    expect(report.errors[0].detail).toMatchObject({ ns: 'tax', reason: 'id shape' });
  });
});

// ---------------------------------------------------------------------------
// tax: — late binding
// ---------------------------------------------------------------------------

describe('tax: late binding', () => {
  it('vector 2 — resolves a term against the whole tree; `surface` stays the TERM', () => {
    const operand = firstOperand(run('@input | classify(tax:node[Kinematics])'));
    expect(operand).toMatchObject({
      kind: 'resolved',
      binding: 'late',
      scopeHint: 'node',
      surface: 'Kinematics',
      id: '01.01.01.01',
      resolvedName: 'Kinematics',
    });
  });

  it('vector 3 — an id scope hint narrows the search', () => {
    const operand = firstOperand(run('@input | classify(tax:01.01[Kinematics])'));
    expect(operand).toMatchObject({ scopeHint: '01.01', id: '01.01.01.01' });
  });

  it('the scope hint NARROWS rather than filtering after the fact', () => {
    // 01.02 is Chemistry: the same term, scoped out of its own subtree, must not
    // resolve. If the hint were applied after picking a winner this would either
    // resolve to a Physics node or produce a different code.
    const report = run('@input | classify(tax:01.02[Kinematics])');
    expect(codes(report)).toEqual(['unknown_operand']);
    expect(report.errors[0].detail).toEqual({ ns: 'tax', surface: 'Kinematics' });
  });

  it('an unresolvable scope hint reports the HINT, not the term', () => {
    const report = run('@input | classify(tax:99.99[Kinematics])');
    expect(codes(report)).toEqual(['unknown_operand']);
    expect(report.errors[0].detail).toEqual({ ns: 'tax', surface: '99.99' });
  });

  it('vector 4 — a comparable-score multimatch is AMBIGUOUS and nothing is chosen', () => {
    const report = run('@input | classify(tax:node[motion])');
    expect(report.valid).toBe(false);
    expect(report.ast).toBeNull();
    expect(codes(report)).toEqual(['ambiguous_operand']);

    const detail = report.errors[0].detail as {
      ns: string;
      surface: string;
      candidates: Array<Record<string, unknown>>;
    };
    expect(detail.ns).toBe('tax');
    expect(detail.surface).toBe('motion');
    expect(detail.candidates.length).toBeGreaterThanOrEqual(2);
    expect(detail.candidates.length).toBeLessThanOrEqual(5);
    for (const candidate of detail.candidates) {
      // §4.4 — the candidate shape is CLOSED, and rank/score is deliberately
      // excluded: publishing an internal bm25 value invites a consumer to
      // re-implement the threshold and diverge from the validator.
      expect(Object.keys(candidate).sort()).toEqual(['id', 'name', 'path']);
      expect(String(candidate.id)).toMatch(/^01\.01\.01\.01\.0[1-4]$/);
    }
  });

  it('vector 5 — zero hits is the uniform unknown_operand, with no candidates', () => {
    const report = run('@input | classify(tax:node[zzzqqxwv])');
    expect(codes(report)).toEqual(['unknown_operand']);
    expect(report.errors[0].detail).toEqual({ ns: 'tax', surface: 'zzzqqxwv' });
  });

  it('vector 20 — an unbuilt FTS index is late_binding_unavailable, never unknown_operand', () => {
    // "index missing", "query malformed" and "genuinely no match" are otherwise
    // the same empty array (searchTaxonomyFts swallows every error to []), and
    // reporting a broken index as "unknown operand" teaches the model to rewrite
    // a term that was correct.
    db.getDb().prepare('DELETE FROM taxonomy_fts').run();
    try {
      const report = run('@input | classify(tax:node[Kinematics])');
      expect(codes(report)).toEqual(['late_binding_unavailable']);
      expect(report.errors[0].detail).toEqual({ ns: 'tax', reason: 'index unavailable' });
    } finally {
      db.rebuildTaxonomyFts(taxonomy.allNodes());
    }
    // and it recovers
    expect(run('@input | classify(tax:node[Kinematics])').valid).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// The ambiguity rule, tuned against measurements rather than asserted as a number
// ---------------------------------------------------------------------------

describe('ambiguity discrimination (the §3.8 threshold, re-tuned)', () => {
  it('the bm25 margin alone leaves vector 2 almost no headroom — which is why the exact-name rule exists', () => {
    const hits = db.searchTaxonomyFts('Kinematics', 32);
    // Measured on the seed spine: the node itself matches on `name`, and all
    // five of its children match on `path`, which also contains "Kinematics".
    expect(hits[0].id).toBe('01.01.01.01');
    const ratio = Math.abs(hits[1].rank - hits[0].rank) / Math.abs(hits[0].rank);
    // ~0.112 — a bare 1.2 points above the 0.10 margin, and that headroom is an
    // artifact of HOW MANY CHILDREN the node happens to have, not of whether the
    // term is unambiguous. A threshold with that little discrimination is a
    // number, not a guarantee.
    expect(ratio).toBeLessThan(0.15);
    expect(ratio).toBeGreaterThan(0.1);
  });

  it('an exact case-insensitive NAME match wins outright over a better-ranked partial', () => {
    // Measured: FTS ranks "Nuclear Physics" and "Particle Physics" ABOVE "Physics"
    // for the term "Physics", and ranks those two identically — so the bm25 rule
    // alone would call `tax:node[Physics]` ambiguous between two nodes that are
    // not the one the term names.
    const hits = db.searchTaxonomyFts('Physics', 32);
    expect(hits[0].id).not.toBe('01.01');
    expect(Math.abs(hits[1].rank - hits[0].rank)).toBeLessThan(0.1 * Math.abs(hits[0].rank));

    const operand = firstOperand(run('@input | classify(tax:node[Physics])'));
    expect(operand.id).toBe('01.01');
    expect(operand.resolvedName).toBe('Physics');
  });

  it('the exact-name rule never manufactures a decision — equal bm25 with no name match stays ambiguous', () => {
    const hits = db.searchTaxonomyFts('motion', 32);
    expect(Math.abs(hits[1].rank - hits[0].rank)).toBeLessThan(0.1 * Math.abs(hits[0].rank));
    expect(codes(run('@input | classify(tax:node[motion])'))).toEqual(['ambiguous_operand']);
  });

  it('a term matching exactly one node resolves without ambiguity', () => {
    // A multi-word term: `ftsQuery` quotes each token separately, so this is an
    // AND over both, and only one node carries both.
    const operand = firstOperand(run('@input | classify(tax:node[Projectile motion])'));
    expect(operand.id).toBe('01.01.01.01.02');
  });
});

// ---------------------------------------------------------------------------
// FTS PAGE STARVATION — the fanout is a page size, not a horizon.
//
// `searchTaxonomyFts` applies `ORDER BY rank LIMIT ?` in SQL, before the scope
// hint or the name rule can be applied. Every measurement below is against the
// real seed spine, and every one of them USED to come back wrong.
// ---------------------------------------------------------------------------

describe('the FTS page never decides what exists (§3.7 / §3.8)', () => {
  it('an exact NAME match is answered from the tree, not from the page it fell off', () => {
    // Measured: "Mathematics" has 44 hits and node 02.01 — named exactly
    // "Mathematics" — ranks 32nd, one past a 32-row page, because bm25
    // systematically prefers the short-named descendants that carry the term in
    // `path`. The exact-name rule exists precisely to resolve this case, and a
    // pre-scoping LIMIT made it unable to fire.
    const page = db.searchTaxonomyFts('Mathematics', 32);
    expect(page.length).toBe(32);
    expect(page.some((h) => h.id === '02.01')).toBe(false);

    expect(firstOperand(run('@input | classify(tax:node[Mathematics])'))).toMatchObject({
      id: '02.01',
      resolvedName: 'Mathematics',
    });
    // 03.01 "Engineering" ranks 50th and is the ONLY node with that exact name.
    expect(firstOperand(run('@input | classify(tax:node[Engineering])')).id).toBe('03.01');
  });

  it('a narrower scope hint is a NARROWING, not a filter over the global page', () => {
    // §3.7 hands the model a narrower hint as THE remedy for ambiguity. Scoping
    // after a global LIMIT made that remedy a dead end: all 32 global hits for
    // "engineering" live under 03.01, so the subtree literally named "Software
    // Engineering" filtered down to zero and answered "operand does not
    // resolve" — teaching the model to rewrite a term that was correct.
    const page = db.searchTaxonomyFts('engineering', 32);
    expect(page.every((h) => !h.id.startsWith('02.02'))).toBe(true);

    const report = run('@input | classify(tax:02.02[engineering])');
    expect(codes(report)).toEqual(['ambiguous_operand']);
    const detail = report.errors[0].detail as { candidates: Array<{ id: string }> };
    expect(detail.candidates.length).toBeLessThanOrEqual(5);
    // every candidate is IN the hinted subtree — the hint narrowed the search
    expect(detail.candidates.every((c) => c.id.startsWith('02.02'))).toBe(true);
    expect(detail.candidates.map((c) => c.id)).toContain('02.02.04');
  });

  it('a single in-subtree hit far down the global ranking still resolves', () => {
    // "technology" has 212 hits; exactly one lives under 06, at rank 171. A
    // 32-row page made `tax:06[technology]` a false unknown_operand.
    expect(db.searchTaxonomyFts('technology', 32).some((h) => h.id.startsWith('06'))).toBe(false);
    expect(firstOperand(run('@input | classify(tax:06[technology])'))).toMatchObject({
      id: '06.02.01.05',
      resolvedName: 'Recording Technology',
    });
  });

  it('still reports a genuine miss as unknown_operand rather than widening forever', () => {
    // The escalation stops at "the index had nothing more to give"; it must not
    // turn an out-of-scope term into a hit.
    const report = run('@input | classify(tax:01.02[Kinematics])');
    expect(codes(report)).toEqual(['unknown_operand']);
    expect(report.errors[0].detail).toEqual({ ns: 'tax', surface: 'Kinematics' });
  });
});

// ---------------------------------------------------------------------------
// §4.4 — the candidate cap, on EVERY branch that emits candidates
// ---------------------------------------------------------------------------

describe('ambiguous_operand candidate cap (§4.4)', () => {
  it('caps the exact-NAME tie at CORTEX_CANDIDATE_CAP, like the bm25 and rel: branches', () => {
    // The seed spine's 12 duplicate names all come in PAIRS, so the cap is
    // never exceeded by seed data alone — but `registerExtNodes` imposes no
    // name-uniqueness rule, and a canonical file tree with a per-service
    // "Overview" node is the ordinary shape ingest produces. Uncapped, this
    // branch published up to CORTEX_FTS_FANOUT (32) ids in one error, against
    // the one quantitative disclosure limit the contract states.
    const { dropped } = taxonomy.registerExtNodes([
      { id: 'ovw', parentId: '', name: 'Overview Fixture Root', description: '', zone: 'anchor' },
      ...Array.from({ length: 8 }, (_, i) => ({
        id: `ovw.svc${i}`,
        parentId: 'ovw',
        name: 'Overview',
        description: '',
        zone: 'free' as const,
      })),
    ]);
    expect(dropped).toEqual([]);
    db.rebuildTaxonomyFts(taxonomy.allNodes());

    const report = run('@input | classify(tax:node[Overview])');
    expect(codes(report)).toEqual(['ambiguous_operand']);
    const detail = report.errors[0].detail as {
      candidates: Array<Record<string, unknown>>;
    };
    expect(detail.candidates.length).toBe(resolve.CORTEX_CANDIDATE_CAP);
    for (const candidate of detail.candidates) {
      expect(Object.keys(candidate).sort()).toEqual(['id', 'name', 'path']);
      expect(candidate.name).toBe('Overview'); // the exact-name branch, not bm25
    }
  });

  it('a two-way exact-name tie on SEED data reports both and picks neither', () => {
    const report = run('@input | classify(tax:node[Logic])');
    expect(codes(report)).toEqual(['ambiguous_operand']);
    const detail = report.errors[0].detail as { candidates: Array<{ id: string }> };
    expect(detail.candidates.map((c) => c.id)).toEqual(['02.03', '05.02.05']);
  });
});

// ---------------------------------------------------------------------------
// rel:
// ---------------------------------------------------------------------------

describe('rel: resolution', () => {
  it('vector 10 — rel:requires IS valid (MECHANICAL_VERBS is a suggestion filter, not a validity filter)', () => {
    const report = run('@input | link(rel:requires)');
    expect(report.valid).toBe(true);
    expect(firstOperand(report)).toMatchObject({
      ns: 'rel',
      kind: 'resolved',
      id: 'requires',
      resolvedName: 'requires',
    });
    expect(warnCodes(report)).toContain('mutating_default_dry_run');
    expect(report.ast!.pipeline.stages[0].effective).toEqual({ dry_run: true });
    // §6/D8 — REPORT, never inject. `params` stays a verbatim record.
    expect(report.ast!.pipeline.stages[0].params).toEqual({});
  });

  it('vector 8/9 (uniformity) — a never-existing verb and a status=proposed verb are byte-identical', () => {
    expect(db.insertProposedRelationType('cortex-planted', 'agent:test')).toBe(true);

    // vector 8 — the plan's own round-1 bad example; `is-a` is not one of the 16.
    const isA = run('@input | link(rel:is-a)');
    expect(codes(isA)).toEqual(['unknown_operand']);
    expect(isA.errors[0].detail).toEqual({ ns: 'rel', surface: 'is-a' });

    // vector 9 — equal-length names, so the entries must be byte-identical
    // after substituting `detail.surface`.
    const planted = run('@input | link(rel:cortex-planted)');
    const absent = run('@input | link(rel:cortex-unknown)');
    expect(codes(planted)).toEqual(['unknown_operand']);
    const normalize = (r: ReturnType<typeof run>) =>
      JSON.stringify(r.errors).split('cortex-planted').join('X').split('cortex-unknown').join('X');
    expect(normalize(planted)).toBe(normalize(absent));
  });

  it('a proposed verb becomes an operand only once moderation CONFIRMS it', () => {
    expect(db.setRelationTypeStatus('cortex-planted', 'confirmed')).toBe(true);
    try {
      expect(run('@input | link(rel:cortex-planted)').valid).toBe(true);
    } finally {
      db.setRelationTypeStatus('cortex-planted', 'proposed');
    }
  });

  it('late binding over the verb vocabulary resolves, refuses and reports ambiguity', () => {
    expect(firstOperand(run('@input | link(rel:verb[depends])')).id).toBe('depends-on');
    // exact type/label match beats substring
    expect(firstOperand(run('@input | link(rel:verb[requires])')).id).toBe('requires');

    const ambiguous = run('@input | link(rel:verb[ize])');
    expect(codes(ambiguous)).toEqual(['ambiguous_operand']);
    const detail = ambiguous.errors[0].detail as { candidates: Array<{ id: string }> };
    expect(detail.candidates.map((c) => c.id).sort()).toEqual(['generalizes', 'specializes']);

    expect(codes(run('@input | link(rel:verb[qqzzxx])'))).toEqual(['unknown_operand']);
  });
});

// ---------------------------------------------------------------------------
// D1 — kg:/ent: are refused at namespace granularity
// ---------------------------------------------------------------------------

describe('D1 — kg:/ent: are never resolved', () => {
  it('vectors 6a/6b — a REAL object id and an absent one produce identical errors', () => {
    const real = '0f9c3e21-4b7a-4f2c-9d51-8ab6e0c72d13';
    db.saveObject('someone-else', {
      id: real,
      type: 'note',
      title: 'A private card the agent surface must not confirm the existence of',
      visibility: 'private',
    });
    // sanity: it really is there, so a resolver that peeked WOULD see it
    expect(db.getObject(real)).not.toBeNull();

    const present = run(`@input | get(kg:${real})`);
    const absent = run('@input | get(kg:11111111-2222-3333-4444-555555555555)');
    expect(codes(present)).toEqual(['namespace_not_resolvable']);
    expect(present.errors[0].detail).toEqual({ ns: 'kg', scope: 'system-ontology' });

    // The whole error entry — offsets included, since the two ids are the same
    // length — is byte-identical. `detail` carries no operand text at all.
    expect(JSON.stringify(present.errors)).toBe(JSON.stringify(absent.errors));
  });

  it('the refusal is constant regardless of operand shape or late binding', () => {
    const details = [
      '@input | get(kg:anything)',
      '@input | get(kg:object[whatever])',
      '@input | map(ent:product)',
      '@input | map(ent:product[červené tričko L])',
    ].map((src) => {
      const report = run(src);
      expect(codes(report)).toEqual(['namespace_not_resolvable']);
      return report.errors[0].detail;
    });
    expect(details[0]).toEqual(details[1]);
    expect(details[2]).toEqual(details[3]);
    expect(details[2]).toEqual({ ns: 'ent', scope: 'system-ontology' });
  });

  it('declares the refusal machine-readably in data.scope', () => {
    const report = run('@input | get(kg:anything)');
    expect(report.scope).toEqual({
      model: 'system-ontology',
      authorizes: false,
      resolved: ['tax', 'rel'],
      unresolved: ['kg', 'ent'],
      deferred: ['db', 'svc', 'doc'],
    });
    // `valid: true` is a statement about MEANING, never about permission.
    expect(run('@input | classify(tax:01.01)').scope.authorizes).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// §5 — deferred namespaces
// ---------------------------------------------------------------------------

describe('deferred (db:/svc:/doc:) operands', () => {
  it('vector 7 — valid but not complete; the operand stays unresolved for Wing', () => {
    const report = run('@input | insert(db:products, dry_run=true)');
    expect(report.valid).toBe(true);
    expect(report.complete).toBe(false);
    expect(report.errors).toEqual([]);
    expect(firstOperand(report)).toMatchObject({
      ns: 'db',
      kind: 'deferred',
      surface: 'products',
      id: null,
      resolvedName: null,
    });
    expect(report.ast!.deferred).toEqual([{ stage: 0, operand: 0, ns: 'db' }]);
    expect(warnCodes(report)).toEqual(['deferred_namespace', 'deferred_program']);
    // explicit dry_run — so NO defaulting warning
    expect(warnCodes(report)).not.toContain('mutating_default_dry_run');
    expect(report.ast!.pipeline.stages[0].effective).toEqual({ dry_run: true });
  });

  it('vector 19 — plan §3’s headline example typechecks and the `?` form is preserved', () => {
    const report = run('@input | insert(db:products, ?hidden=true, dry_run=true)');
    expect(report.valid).toBe(true);
    expect(report.ast!.pipeline.stages[0].params.hidden).toMatchObject({
      value: true,
      defaulted: true,
    });
    expect(report.ast!.pipeline.stages[0].params.dry_run).toMatchObject({
      value: true,
      defaulted: false,
    });
  });

  it('vector 11 — the dry-run default is REPORTED, never injected into params', () => {
    const report = run('@input | delete(db:products)');
    expect(report.valid).toBe(true);
    expect(report.ast!.pipeline.stages[0].params).toEqual({});
    expect(report.ast!.pipeline.stages[0].effective).toEqual({ dry_run: true });
    expect(warnCodes(report)).toContain('mutating_default_dry_run');
  });

  it('vector 16 — a deferred namespace in a NON-accepting slot is still rejected structurally', () => {
    const report = run('@input | classify(db:products)');
    expect(codes(report)).toEqual(['namespace_not_accepted']);
    expect(report.errors[0].detail).toEqual({
      opcode: 'classify',
      ns: 'db',
      allowed: ['tax', 'kg'],
    });
  });

  it('a mixed program indexes every deferred operand for Wing', () => {
    const report = run('@input | classify(tax:01.01) | insert(db:products) | route(svc:mailer)');
    expect(report.valid).toBe(true);
    expect(report.complete).toBe(false);
    expect(report.ast!.deferred).toEqual([
      { stage: 1, operand: 0, ns: 'db' },
      { stage: 2, operand: 0, ns: 'svc' },
    ]);
    expect(report.ast!.pipeline.stages[0].operands[0].id).toBe('01.01');
  });
});

// ---------------------------------------------------------------------------
// D4/D5 — the binding stamp
// ---------------------------------------------------------------------------

describe('ast.binding (vector 22)', () => {
  it('stamps the three drift axes plus a TTL window', () => {
    const report = run('@input | classify(tax:01.01)', 900);
    const binding = report.ast!.binding!;
    expect(binding.ontologyVersion).toBe(ontologyVersion.cortexOntologyVersion());
    expect(binding.ontologyVersion).toMatch(/^onto1:[0-9a-f]{16}$/);
    expect(binding.databaseId).toBe(db.getDbIdentity()!.id);
    expect(binding.opcodeRegistryHash).toBe(opcodes.cortexRegistryHash());
    expect(binding.ttlSeconds).toBe(900);
    expect(Date.parse(binding.expiresAt) - Date.parse(binding.validatedAt)).toBe(900_000);
  });

  it('is stamped only on a valid program', () => {
    expect(run('@input | classify(tax:99.99)').ast).toBeNull();
  });

  it('carries the source verbatim, so a dispatcher can revalidate by re-POSTing it', () => {
    const source = '@input | classify(tax:node[Kinematics])';
    expect(run(source).ast!.source).toBe(source);
  });
});

describe('D4 — the ontology fingerprint', () => {
  it('is stable across calls when the vocabulary is stable', () => {
    expect(ontologyVersion.cortexOntologyVersion()).toBe(ontologyVersion.cortexOntologyVersion());
  });

  it('moves when the taxonomy grows', () => {
    const before = ontologyVersion.cortexOntologyVersion();
    taxonomy.registerExtNodes([
      { id: 'cxfix.grown', parentId: 'cxfix', name: 'Grown', description: '', zone: 'free' },
    ]);
    expect(ontologyVersion.cortexOntologyVersion()).not.toBe(before);
  });

  it('does NOT move for a description edit — the one place it is deliberately coarse', () => {
    const before = ontologyVersion.cortexOntologyVersion();
    expect(
      taxonomy.applyDescriptionOverride({ nodeId: '01.01', descriptionEn: 'edited '.repeat(4) }),
    ).toBe(true);
    expect(ontologyVersion.cortexOntologyVersion()).toBe(before);
  });

  it('does NOT move for an agent-planted proposed verb, but DOES when it is confirmed', () => {
    const before = ontologyVersion.cortexOntologyVersion();
    db.insertProposedRelationType('cortex-drift-probe', 'agent:test');
    expect(ontologyVersion.cortexOntologyVersion()).toBe(before);

    db.setRelationTypeStatus('cortex-drift-probe', 'confirmed');
    expect(ontologyVersion.cortexOntologyVersion()).not.toBe(before);
    db.setRelationTypeStatus('cortex-drift-probe', 'proposed');
    expect(ontologyVersion.cortexOntologyVersion()).toBe(before);
  });

  it('is cheap enough to compute fresh on every call (the reason it is not cached)', () => {
    ontologyVersion.cortexOntologyVersion(); // warm the JIT, not a cache
    const started = performance.now();
    for (let i = 0; i < 20; i += 1) ontologyVersion.cortexOntologyVersion();
    const perCall = (performance.now() - started) / 20;
    // Measured at ~0.18 ms; the bound is deliberately loose so this pins the
    // ORDER OF MAGNITUDE (catching an accidental O(n²) or a per-node query)
    // without flaking on a loaded CI box.
    expect(perCall).toBeLessThan(25);
  });

  it('serializes the vocabulary the RESOLVER uses — dropped ext rows are absent', () => {
    const canonical = ontologyVersion.canonicalOntologyVocabulary();
    expect(canonical).toContain('t\t01.01\t01\tPhysics');
    expect(canonical).toContain('r\trequires\tseed\trequires');
    expect(canonical).toContain('r\tanalogous-to\tseed\tanalogous to');
    expect(canonical).not.toContain('orphan.dropped');
    expect(canonical).not.toContain('cortex-planted'); // status='proposed'
    expect(canonical.endsWith('\n')).toBe(false);
  });

  it('MOVES on a verb LABEL edit — the `rel:` half of the rename rule', () => {
    // A label is not decoration: `resolveVerb` matches the bracket term against
    // it and `bind` writes it into `operand.resolvedName`, so a label edit both
    // changes what late binding resolves to and staleens every AST that
    // recorded it. knowledge/ingest.mjs UPSERTs `label` from the checked-in SoT
    // on every run, so this is an ordinary operation, not a hypothetical.
    const before = ontologyVersion.cortexOntologyVersion();
    const original = db.getRelationType('defines')!.label;
    expect(codes(run('@input | link(rel:verb[renamed])'))).toEqual(['unknown_operand']);

    db.getDb().prepare('UPDATE relation_types SET label = ? WHERE type = ?').run('renamed thing', 'defines');
    try {
      // the resolver's answer changed…
      expect(firstOperand(run('@input | link(rel:verb[renamed])'))).toMatchObject({
        id: 'defines',
        resolvedName: 'renamed thing',
      });
      // …so the drift signal Wing revalidates on MUST have changed with it
      expect(ontologyVersion.cortexOntologyVersion()).not.toBe(before);
    } finally {
      db.getDb().prepare('UPDATE relation_types SET label = ? WHERE type = ?').run(original, 'defines');
    }
    expect(ontologyVersion.cortexOntologyVersion()).toBe(before);
  });
});

// ---------------------------------------------------------------------------
// §7.1 — ZERO SIDE EFFECTS
// ---------------------------------------------------------------------------

describe('zero side effects', () => {
  it('a full sweep of programs leaves every table row-count untouched', () => {
    const tables = (
      db
        .getDb()
        .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        .all() as Array<{ name: string }>
    ).map((r) => r.name);
    expect(tables.length).toBeGreaterThan(5);

    const census = () => {
      const out: Record<string, number> = {};
      for (const name of tables) {
        try {
          out[name] = (
            db.getDb().prepare(`SELECT COUNT(*) c FROM "${name}"`).get() as { c: number }
          ).c;
        } catch {
          out[name] = -1; // shadow/virtual tables that do not answer COUNT(*)
        }
      }
      return out;
    };

    const before = census();
    for (const source of [
      '@input | classify(tax:01.01)',
      '@input | classify(tax:node[Kinematics])',
      '@input | classify(tax:node[motion])',
      '@input | classify(tax:node[zzzqqxwv])',
      '@input | link(rel:requires)',
      '@input | link(rel:verb[depends])',
      '@input | get(kg:whatever)',
      '@input | insert(db:products, ?hidden=true, commit=true)',
      '@input | frobnicate(tax:01)',
      '@input.map(tax:01.01)',
    ]) {
      run(source);
    }
    expect(census()).toEqual(before);
  });
});

// ---------------------------------------------------------------------------
// Report shape + the phase ordering
// ---------------------------------------------------------------------------

describe('report assembly', () => {
  it('a phase-3 failure never runs phase 4 — no resolution error joins a structural one', () => {
    // `frobnicate` is not an opcode AND `tax:99.99` does not resolve. Only the
    // structural error may appear: resolution must not have run.
    const report = run('@input | frobnicate(tax:99.99)');
    expect(codes(report)).toEqual(['unknown_opcode']);
  });

  it('a parse failure is the SOLE error entry (vectors 12 and 13)', () => {
    const truncatedCall = run('@input | map(tax:01.01');
    expect(codes(truncatedCall)).toEqual(['syntax_error']);
    expect(truncatedCall.errors[0].offset).toBe(22);
    expect(truncatedCall.errors[0].detail).toEqual({ found: '<eof>', expected: [')', ','] });

    const dotted = run('@input.map(tax:01.01)');
    expect(codes(dotted)).toEqual(['syntax_error']);
    expect(dotted.errors[0].offset).toBe(6);
    // §7.6 — NOT rewritten to `@input | map(…)`. Guessing intent is a normalizer.
    expect(dotted.ast).toBeNull();
  });

  it('collects EVERY resolution error in one round-trip (phase 4 does not stop at the first)', () => {
    const report = run('@input | classify(tax:99.99) | link(rel:is-a, rel:also-not-real)');
    expect(codes(report)).toEqual(['unknown_operand', 'unknown_operand', 'unknown_operand']);
    expect(report.errors.map((e) => e.stage)).toEqual([0, 1, 1]);
  });

  it('caps resolution errors at the §3.6 bound and flags the truncation', () => {
    const stages = Array.from({ length: 12 }, () => 'link(rel:nope-a, rel:nope-b)').join(' | ');
    const report = run(`@input | ${stages}`);
    expect(report.errors).toHaveLength(lang.CORTEX_LIMITS.errors);
    expect(report.truncated).toBe(true);
  });

  it('vector 21 — a reserved scope word without a term is malformed, not a lookup', () => {
    const report = run('@input | classify(tax:node)');
    expect(codes(report)).toEqual(['malformed_operand']);
    expect(report.errors[0].detail).toMatchObject({
      reason: 'reserved scope word requires a term',
    });
  });

  it('vector 14 — unknown_opcode suggestions come only from the published registry', () => {
    const report = run('@input | frobnicate(tax:01)');
    expect(codes(report)).toEqual(['unknown_opcode']);
    expect(report.errors[0].detail).toEqual({ opcode: 'frobnicate', didYouMean: [] });
  });

  it('vector 15 — arity is counted over ENTITY args only', () => {
    const report = run('@input | classify()');
    expect(codes(report)).toEqual(['arity_error']);
    expect(report.errors[0].detail).toEqual({ opcode: 'classify', min: 1, max: 1, got: 0 });
  });
});

// ---------------------------------------------------------------------------
// The request envelope (shared/contracts/cortex.ts)
// ---------------------------------------------------------------------------

describe('request envelope', () => {
  it('requires a string source and clamps ttlSeconds instead of rejecting it', async () => {
    const { cortexValidateRequestSchema } = await import('../shared/contracts/cortex');
    expect(cortexValidateRequestSchema.safeParse({}).success).toBe(false);
    expect(cortexValidateRequestSchema.safeParse({ source: 42 }).success).toBe(false);

    const parsed = (body: unknown) => {
      const r = cortexValidateRequestSchema.safeParse(body);
      expect(r.success).toBe(true);
      return r.success ? r.data : null;
    };
    expect(parsed({ source: '@input' })!.ttlSeconds).toBe(900);
    expect(parsed({ source: '@input', ttlSeconds: 1 })!.ttlSeconds).toBe(60);
    expect(parsed({ source: '@input', ttlSeconds: 999_999 })!.ttlSeconds).toBe(3600);
    expect(parsed({ source: '@input', ttlSeconds: 1200 })!.ttlSeconds).toBe(1200);
  });

  it('an empty source is a typed syntax_error report, not a thrown request', () => {
    const report = run('');
    expect(codes(report)).toEqual(['syntax_error']);
    expect(report.errors[0].offset).toBe(0);
  });

  it('an over-length source is program_too_large, reported before tokenizing', () => {
    const report = run(`@input | classify(tax:node[${'x'.repeat(5000)}])`);
    expect(codes(report)).toEqual(['program_too_large']);
    expect(report.errors[0].detail).toMatchObject({ bound: 'source_length', limit: 4096 });
  });
});
