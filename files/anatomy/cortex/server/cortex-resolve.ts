/**
 * cortex-resolve — phase 4 of `POST /agent/v1/validate`: operand resolution
 * against the LIVE ontology (docs/specs/cortex-validate.md §3.8, §4.3, D1).
 *
 * READ-ONLY, and that is a hard requirement rather than a happy accident
 * (spec §7.1). Every call in this module is a SELECT or an in-memory map
 * lookup. Nothing here writes a row, proposes anything, embeds anything, warms
 * an index or touches a cache a caller could observe. `validate` must stay safe
 * to call in a loop.
 *
 * The identity model (D1) is enforced HERE, as data, from
 * `NAMESPACE_POLICY` in ./cortex-opcodes:
 *
 *   tax, rel        resolved   — system scope. Legal ONLY because both layers are
 *                               ownerless, have no visibility column, and are
 *                               already enumerable wholesale by the same RO
 *                               bearer via GET /agent/v1/taxonomy/search and
 *                               GET /agent/v1/relations. `validate` answers
 *                               questions the caller can already answer with two
 *                               existing GETs: no new capability, no new
 *                               disclosure. That strict-subset argument is the
 *                               WHOLE justification — it does not generalise.
 *   kg, ent         unresolved — a constant, operand-INDEPENDENT
 *                               `namespace_not_resolvable`, emitted before any
 *                               lookup. NO DATABASE CALL IS MADE. Issuing the
 *                               lookup and discarding the result would keep the
 *                               timing oracle, which is the thing being closed.
 *   db, svc, doc    deferred   — Wing's phase 2. Skipped entirely; this module
 *                               must never learn which resources exist.
 *
 * The uniform-error rule, stated as an invariant the suite tests: for any two
 * inputs differing only in the IDENTITY of a shape-legal operand within one
 * namespace, the emitted entries are byte-identical after substituting
 * `detail.surface`. An absent `tax:` id and a `taxonomy_nodes_ext` row that
 * `registerExtNodes` dropped both yield `unknown_operand`; a `rel:` verb that
 * never existed and one sitting at `status='proposed'` both yield
 * `unknown_operand`.
 *
 * Phase 4 runs ONLY when phases 2 and 3 produced no errors (§4.3), so every
 * operand reaching this module is already grammar-legal and shape-legal.
 */
import * as db from './db';
import { allNodes, getAncestors, getNode, type FlatNode } from './taxonomy';
import { NAMESPACE_POLICY, RESERVED_SCOPE_WORDS, CORTEX_SCOPE } from './cortex-opcodes';
import { cortexIssue, type CortexAst, type CortexAstOperand, type CortexIssue } from './cortex-lang';

// ---------------------------------------------------------------------------
// Tunables — every one of them pinned by server/cortex-resolve.test.ts
// ---------------------------------------------------------------------------

/** How many IN-SCOPE FTS hits the ranking rule wants before it stops fetching.
 *  Over-fetch: a subtree-scoped search (`tax:01.01[…]`) discards hits outside
 *  the subtree, and a fanout equal to the candidate cap would let five
 *  out-of-scope hits starve a correct in-scope one.
 *
 *  This is a PAGE SIZE, not a ceiling on what the search may see — see
 *  `scopedHits`. A fixed `LIMIT 32` applied in SQL, before the scope is known,
 *  is not "over-fetch", it is starvation with a bigger constant: on the seed
 *  spine every one of the 32 global hits for "engineering" lives under `03.01`,
 *  so `tax:02.02[engineering]` (the subtree literally named "Software
 *  Engineering") filtered down to zero and was reported as `unknown_operand` —
 *  teaching the model to rewrite a term that was correct, the single worst
 *  repair-loop lesson available, and reached through the very scope hint §3.7
 *  hands back as the remedy for `ambiguous_operand`. */
export const CORTEX_FTS_FANOUT = 32;

/** The hard ceiling on the escalation in `scopedHits`. A subtree-scoped query
 *  re-fetches a wider page until the SCOPE is covered rather than until the
 *  TREE is; this bounds the worst case (4 queries: 32 → 128 → 512 → 4096) so a
 *  grown corpus cannot turn a read-only validate into a table scan per operand.
 *  4096 is comfortably above the ~1840-node target corpus, so on any tree this
 *  system is planned for, "exhausted" is what stops the loop, not this. */
export const CORTEX_FTS_MAX_FANOUT = 4096;

/** §4.4 — candidate lists are capped at 5 and carry `{id, name, path}` only. */
export const CORTEX_CANDIDATE_CAP = 5;

/**
 * §3.8 step 5 — the ambiguity margin, as a fraction of |best rank|.
 *
 * fts5 `rank` is bm25: NEGATIVE, more negative = better. Let `r0` be the best
 * and `r1` the runner-up; if `|r1 - r0| < MARGIN * |r0|` the two are
 * "comparable" and the validator REFUSES TO CHOOSE.
 *
 * The spec is explicit that 0.10 is "a starting value, not a law" and must be
 * re-tuned against the discrimination pair (vectors 4 and 5). It survived
 * tuning unchanged — see the tuning block in server/cortex-resolve.test.ts,
 * which asserts both directions (an ambiguous term stays ambiguous, a
 * unique-name term resolves) rather than only that the number is 0.1.
 */
export const CORTEX_AMBIGUITY_MARGIN = 0.1;

// ---------------------------------------------------------------------------
// Candidates
// ---------------------------------------------------------------------------

/**
 * §4.4 — the CLOSED candidate shape. `rank`/`score` is deliberately excluded:
 * it is an internal bm25 value with no cross-query meaning, and publishing it
 * invites a consumer to re-implement the threshold and diverge from the
 * validator that produced the AST.
 *
 * Safe to publish under D1 because candidates can only ever come from `tax:` or
 * `rel:` — `kg:`/`ent:` never reach the resolver, so no instance-level candidate
 * list can be assembled even by mistake.
 *
 * FORWARD RULE (written now so P3 cannot get it wrong): the moment `kg:` becomes
 * resolvable, candidate lists must be filtered through `db.canReadObject`
 * BEFORE the list is assembled — not filtered after, not counted before. A
 * count, a score, a "N more" hint or a truncation marker computed over
 * unfiltered results is the same disclosure the uniform error closes.
 */
export interface CortexCandidate {
  id: string;
  name: string;
  /** ancestry, EXCLUDING the node itself — `FlatNode.path`, exactly as
   *  `GET /agent/v1/taxonomy/search` already publishes it. (Spec §4.4's
   *  illustrative candidate shows the node's own name appended; that is the
   *  same off-by-one class as the §3.3 span erratum. The live field is the
   *  contract, and a second path convention on one surface would be worse than
   *  an illustration that disagrees with it.) Empty for `rel:`, which has no
   *  ancestry. */
  path: string;
}

// ---------------------------------------------------------------------------
// Entry points
// ---------------------------------------------------------------------------

interface ResolveContext {
  source: string;
  errors: CortexIssue[];
}

/**
 * Resolve every operand of `ast` IN PLACE and return the phase-4 errors.
 *
 * Mutation is intentional: `resolvedName` is "the name that id had at
 * resolution time" (plan §6.3, drift invalidation) and belongs on the operand
 * node, not in a side table the report would have to zip back together. The
 * caller discards the AST entirely when any error is returned (§3.2: there is no
 * half-valid program), so a partially-resolved AST is never observable.
 */
export function resolveCortexOperands(source: string, ast: CortexAst): CortexIssue[] {
  const ctx: ResolveContext = { source, errors: [] };

  ast.pipeline.stages.forEach((stage) => {
    for (const operand of stage.operands) {
      const policy = NAMESPACE_POLICY[operand.ns];

      if (policy === 'deferred') {
        // §5 — KEAP has already said everything it is allowed to say about a
        // deferred operand (it is a well-formed dotted id in a slot whose opcode
        // declares the namespace). `kind` stays "deferred", `id` and
        // `resolvedName` stay null, and Wing fills them in phase 2.
        continue;
      }

      if (policy === 'unresolved') {
        // D1 — constant per namespace, computed from the namespace token alone.
        // Reached for `kg:` and `ent:`, existing or not, readable or not.
        ctx.errors.push(
          cortexIssue(
            'namespace_not_resolvable',
            'this namespace is not resolvable at the declared validation scope',
            { ns: operand.ns, scope: CORTEX_SCOPE.model },
            { source, stage: stage.index, span: operand.span },
          ),
        );
        continue;
      }

      if (operand.ns === 'tax') resolveTaxonomy(operand, stage.index, ctx);
      else if (operand.ns === 'rel') resolveVerb(operand, stage.index, ctx);
    }
  });

  return ctx.errors;
}

// ---------------------------------------------------------------------------
// tax:
// ---------------------------------------------------------------------------

function resolveTaxonomy(operand: CortexAstOperand, stage: number, ctx: ResolveContext): void {
  if (operand.binding === 'exact') {
    // §3.8 — `getNode` is the ONLY oracle. Never query `taxonomy_nodes_ext`
    // directly: `registerExtNodes` deliberately drops rows whose parent never
    // resolved or whose root id is not a bare slug, and a table query would make
    // those orphans resolvable again, reintroducing exactly the silent-orphan
    // class the boot fixpoint exists to prevent.
    const node = getNode(operand.surface);
    if (!node) {
      ctx.errors.push(unknownOperand(operand, stage, ctx));
      return;
    }
    operand.kind = 'resolved';
    operand.id = node.id;
    operand.resolvedName = node.name;
    return;
  }

  // --- late binding -------------------------------------------------------
  const hint = operand.scopeHint ?? '';
  const wholeTree = hint === RESERVED_SCOPE_WORDS.tax;

  if (!wholeTree && !getNode(hint)) {
    // D6 — a scope hint that is not the reserved word is itself a `tax:` id, and
    // the tree is public to this token, so reporting it is consistent with §1.3.
    // `surface` is the HINT, not the term: that is the token the model must fix.
    ctx.errors.push(
      cortexIssue(
        'unknown_operand',
        'operand does not resolve',
        { ns: 'tax', surface: hint },
        { source: ctx.source, stage, span: operand.span },
      ),
    );
    return;
  }

  // §3.8 step 2 — the health check MUST precede the search. `searchTaxonomyFts`
  // swallows every error to `[]` (server/db.ts:1404) and `ftsQuery` returns ''
  // (→ `[]`) for whitespace-only input, so "index missing", "query malformed"
  // and "genuinely no match" are otherwise the same empty array. Reporting a
  // broken index as `unknown_operand` teaches the model to rewrite a term that
  // was correct — the single worst repair-loop lesson available.
  if (db.countRows('taxonomy_fts') <= 0) {
    ctx.errors.push(
      cortexIssue(
        'late_binding_unavailable',
        'the taxonomy full-text index is unavailable; late binding cannot run',
        { ns: 'tax', reason: 'index unavailable' },
        { source: ctx.source, stage, span: operand.span },
      ),
    );
    return;
  }

  // REFINEMENT of §3.8 step 5, and the one place this stage adds a rule the
  // spec does not state. An exact, case-insensitive match on a node's NAME is a
  // categorically stronger signal than a bm25 ranking, and it is checked first:
  //
  //   - Vector 2, `tax:node[Kinematics]`, must resolve uniquely. But
  //     "Kinematics" is also a token in the `path` column of all five of that
  //     node's children, so a pure-bm25 rule makes the correct answer's margin
  //     over its own children an artifact of relative column lengths in the
  //     index — i.e. the vector would pass or fail depending on how many
  //     siblings exist, not on whether the term is unambiguous.
  //   - It never manufactures a decision: if TWO nodes share the name exactly,
  //     the term genuinely is ambiguous and this branch reports it as such.
  //   - It cannot rescue vector 4 (`motion`): no node is named "motion", so the
  //     bm25 margin rule below is what runs, unchanged.
  //
  // It is answered from the TREE (`allNodes`), not from an FTS page. A name
  // equality test is not a ranking question and must not inherit a ranking
  // question's truncation: node `02.01` is named exactly "Mathematics" and sits
  // at position 32 of the global FTS result for "Mathematics" — one past the
  // page — so the rule whose entire purpose is to make that case resolve could
  // not fire, and no scope hint could rescue it, because the hint was applied
  // after the LIMIT. Same oracle as everywhere else in this module (`getNode` /
  // `allNodes`), so a dropped ext row stays unresolvable here too.
  const needle = operand.surface.trim().toLowerCase();
  const exact = nodesNamedExactly(needle, hint, wholeTree);
  if (exact.length === 1) {
    bind(operand, exact[0].id, exact[0].name);
    return;
  }
  if (exact.length > 1) {
    ctx.errors.push(
      ambiguous(operand, stage, ctx, exact.slice(0, CORTEX_CANDIDATE_CAP).map(candidateOf)),
    );
    return;
  }

  const scoped = scopedHits(operand.surface, hint, wholeTree);
  if (scoped.length === 0) {
    ctx.errors.push(unknownOperand(operand, stage, ctx));
    return;
  }

  const best = scoped[0].hit.rank;
  const runnerUp = scoped[1]?.hit.rank;
  if (runnerUp !== undefined && Math.abs(runnerUp - best) < CORTEX_AMBIGUITY_MARGIN * Math.abs(best)) {
    // THE VALIDATOR DOES NOT CHOOSE. A valid-but-wrong id is indistinguishable
    // from a correct one after the fact — it typechecks, it dispatches, and the
    // damage is silent. That is precisely the failure class
    // knowledge/ingest.mjs's identity-drift detector exists for, and the reason
    // late binding is allowed to exist at all. The remedy handed back is a
    // narrower scope hint (`tax:01.01[motion]`), which is a single-token
    // correction against the candidate list this error carries.
    ctx.errors.push(
      ambiguous(operand, stage, ctx, scoped.slice(0, CORTEX_CANDIDATE_CAP).map((row) => candidateOf(row.node))),
    );
    return;
  }

  bind(operand, scoped[0].node.id, scoped[0].node.name);
}

interface ScopedHit {
  hit: db.FtsHit;
  node: FlatNode;
}

/**
 * The in-scope FTS page, fetched until the SCOPE is covered.
 *
 * `db.searchTaxonomyFts` applies `ORDER BY rank LIMIT ?` in SQL, before the
 * scope hint is known to it, so a single fixed fetch answers "the best N in the
 * TREE" when the question asked was "the best N in THIS SUBTREE". Those differ
 * catastrophically whenever a term is popular outside the hinted subtree:
 * "technology" has 212 hits on the seed spine and the single one inside `06`
 * ranks 171st, so one page of 32 made `tax:06[technology]` a false
 * `unknown_operand`.
 *
 * So: widen the page until either enough IN-SCOPE hits exist to rank
 * (`CORTEX_FTS_FANOUT` of them), or the index is exhausted (a short page proves
 * there is no more), or the ceiling is hit. The whole-tree case (`tax:node[…]`,
 * the overwhelming majority) never escalates — its first page is already fully
 * in scope — so this costs one query there, exactly as before.
 *
 * Still read-only: `searchTaxonomyFts` is a SELECT and re-running it with a
 * larger LIMIT is still a SELECT.
 */
function scopedHits(surface: string, hint: string, wholeTree: boolean): ScopedHit[] {
  let limit = CORTEX_FTS_FANOUT;
  for (;;) {
    // Call `db.searchTaxonomyFts` DIRECTLY. The existing helper `searchNodes`
    // (server/agent.ts:108) throws `rank` away, and `rank` is the only signal an
    // ambiguity check has. Never `hybridSearch`: its score is RRF
    // `1/(60+rank+1)`, where adjacent ranks differ by ~0.00026 and the value is
    // bounded to ~0.016 regardless of match quality — a threshold built on it
    // fires on every query or on none.
    const page = db.searchTaxonomyFts(surface, limit);
    const scoped = page
      .map((hit) => ({ hit, node: getNode(hit.id) }))
      .filter(
        (row): row is ScopedHit => row.node !== null && inSubtree(row.hit.id, hint, wholeTree),
      )
      .sort((a, b) => a.hit.rank - b.hit.rank); // bm25: negative, ascending = best first

    if (scoped.length >= CORTEX_FTS_FANOUT) return scoped;
    if (page.length < limit) return scoped; // the index had nothing more to give
    if (limit >= CORTEX_FTS_MAX_FANOUT) return scoped;
    limit = Math.min(limit * 4, CORTEX_FTS_MAX_FANOUT);
  }
}

/** Every node in scope whose NAME equals `needle` (already trimmed and
 *  lower-cased), ordered by id so the candidate list is deterministic rather
 *  than dependent on tree-insertion order. */
function nodesNamedExactly(needle: string, hint: string, wholeTree: boolean): FlatNode[] {
  if (!needle) return [];
  return allNodes()
    .filter((node) => node.name.trim().toLowerCase() === needle && inSubtree(node.id, hint, wholeTree))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

/** Subtree containment via the ancestor walk (`getAncestors`), NOT a dotted
 *  string prefix. A prefix test bakes in an id-shape assumption that grown slug
 *  roots do not have to honour, and the tree is the authority on ancestry. */
function inSubtree(id: string, hint: string, wholeTree: boolean): boolean {
  if (wholeTree) return true;
  if (id === hint) return true;
  return getAncestors(id).some((a) => a.id === hint);
}

function candidateOf(node: { id: string; name: string; path: string }): CortexCandidate {
  return { id: node.id, name: node.name, path: node.path };
}

// ---------------------------------------------------------------------------
// rel:
// ---------------------------------------------------------------------------

/** §3.8 — a verb is an operand IFF the row exists AND its status is live.
 *
 *  `'proposed'` rows are plantable by any RW bearer POSTing an unknown type to
 *  `/agent/v1/relations`, and a vocabulary writable by the pipeline that
 *  consumes it is not a vocabulary — so `'proposed'` yields the SAME
 *  `unknown_operand` as a verb that never existed (the uniformity rule).
 *
 *  Do NOT validate against the `RelationStatus` union (server/db.ts:2507,
 *  `'proposed'|'confirmed'|'rejected'`): that enum describes relation ROWS, not
 *  type rows, and `'seed'` is not a member of it — using it would reject all 16
 *  seeded verbs.
 *
 *  And `rel:requires` IS valid. `MECHANICAL_VERBS = new Set(['requires'])`
 *  (server/agent.ts:340) is a SUGGESTION-time filter for the classifier only;
 *  the verb lists, renders and moderates everywhere else and the system actively
 *  writes it. Copying that filter here would reject a legitimate seed predicate. */
function liveVerbs(): Array<{ type: string; label: string }> {
  return db
    .listRelationTypes()
    .filter((row) => row.status === 'seed' || row.status === 'confirmed')
    .map((row) => ({ type: row.type, label: row.label }));
}

function resolveVerb(operand: CortexAstOperand, stage: number, ctx: ResolveContext): void {
  if (operand.binding === 'exact') {
    const row = db.getRelationType(operand.surface);
    if (!row || (row.status !== 'seed' && row.status !== 'confirmed')) {
      ctx.errors.push(unknownOperand(operand, stage, ctx));
      return;
    }
    bind(operand, row.type, row.label);
    return;
  }

  // Late binding over the verb vocabulary (D6: the `verb` scope hint means
  // "search the predicates by type and label"). Deliberately NOT FTS: the
  // vocabulary is ~16 rows held in one table, an FTS index over it does not
  // exist, and building one would be a write. Exact-then-substring over two
  // fields is total, deterministic and needs no index.
  const needle = operand.surface.trim().toLowerCase();
  const vocabulary = liveVerbs();
  const exact = vocabulary.filter(
    (v) => v.type.toLowerCase() === needle || v.label.trim().toLowerCase() === needle,
  );
  const tier = exact.length > 0
    ? exact
    : vocabulary.filter(
        (v) => v.type.toLowerCase().includes(needle) || v.label.toLowerCase().includes(needle),
      );

  if (tier.length === 0) {
    ctx.errors.push(unknownOperand(operand, stage, ctx));
    return;
  }
  if (tier.length > 1) {
    // Same refusal discipline as `tax:`: several verbs match the term equally
    // well, so the validator reports them and picks none.
    ctx.errors.push(
      ambiguous(
        operand,
        stage,
        ctx,
        tier.slice(0, CORTEX_CANDIDATE_CAP).map((v) => ({ id: v.type, name: v.label, path: '' })),
      ),
    );
    return;
  }
  bind(operand, tier[0].type, tier[0].label);
}

// ---------------------------------------------------------------------------
// Shared issue constructors
// ---------------------------------------------------------------------------

function bind(operand: CortexAstOperand, id: string, resolvedName: string): void {
  operand.kind = 'resolved';
  operand.id = id;
  operand.resolvedName = resolvedName;
  // `surface` is NEVER rewritten — it is the text the model actually wrote, and
  // the AST carrying BOTH the surface term and the resolved id is what makes
  // drift auditable after the fact (plan §3).
}

/** THE uniform one. `detail` is `{ns, surface}` and nothing else: no candidates,
 *  no "did you mean", no count, no near-miss hint. Anything incidental in here
 *  is the disclosure that the uniformity rule exists to close. */
function unknownOperand(operand: CortexAstOperand, stage: number, ctx: ResolveContext): CortexIssue {
  return cortexIssue(
    'unknown_operand',
    'operand does not resolve',
    { ns: operand.ns, surface: operand.surface },
    { source: ctx.source, stage, span: operand.span },
  );
}

function ambiguous(
  operand: CortexAstOperand,
  stage: number,
  ctx: ResolveContext,
  candidates: CortexCandidate[],
): CortexIssue {
  return cortexIssue(
    'ambiguous_operand',
    'operand matches several entries at comparable scores; narrow the scope hint',
    { ns: operand.ns, surface: operand.surface, candidates },
    { source: ctx.source, stage, span: operand.span },
  );
}
