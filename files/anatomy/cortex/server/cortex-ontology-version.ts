/**
 * cortex-ontology-version — Decision D4: a content hash of the LIVE operand
 * vocabulary, stamped into every AST as `binding.ontologyVersion` and published
 * additively at `GET /agent/v1/health` as `ontology.version`.
 *
 * Why a hash and not a number: there is no ontology version in this codebase.
 * `db.ontologyStats()` publishes four COUNTS; `knowledge/ontology/manifest.json`
 * carries a FILE-FORMAT version that the server never reads. A declared version
 * would need a bump discipline and would go stale the first time someone forgot.
 * A derived fingerprint cannot go stale.
 *
 * Canonical serialization — LF-joined, no trailing newline:
 *
 *   t \t <id> \t <parentId | "-"> \t <name>     every node in allNodes(), id ASC
 *   r \t <type> \t <status> \t <label>          relation_types with status IN
 *                                               ('seed','confirmed'), type ASC
 *
 * then `onto1:` + the first 16 hex chars of sha256.
 *
 * READ-ONLY. This module issues two SELECTs and touches nothing — `validate` has
 * zero side effects (spec §7.1) and this is on its hot path.
 */
import { createHash } from 'node:crypto';
import * as db from './db';
import { allNodes } from './taxonomy';

/** Byte-wise, locale-INDEPENDENT ordering. `localeCompare` would make the
 *  fingerprint depend on the container's ICU locale, so two identical corpora on
 *  two hosts would disagree — which is precisely the false-drift signal this
 *  hash exists to avoid producing. */
function byCodeUnit(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** The live vocabulary filter used twice already in this codebase
 *  (server/agent.ts:432 and :562). `'proposed'` rows are agent-grown: any RW
 *  bearer can plant one by POSTing an unknown type to `/agent/v1/relations`, so
 *  including them would let the pipeline that CONSUMES the vocabulary move the
 *  version of the vocabulary. */
function isLiveVerbStatus(status: string): boolean {
  return status === 'seed' || status === 'confirmed';
}

/**
 * The canonical serialization. Exported so the unit suite can assert the
 * composition directly rather than only through its digest — a hash test that
 * only compares two hashes cannot tell you WHICH field stopped mattering.
 *
 * Field choices, each load-bearing:
 *  - `allNodes()` (server/taxonomy.ts:151), NOT the `taxonomy_nodes_ext` table.
 *    `registerExtNodes` deliberately DROPS rows whose parent never resolves or
 *    whose root id is not a bare slug, and `getNode` is the only oracle the
 *    resolver uses. The fingerprint must describe the vocabulary validate
 *    actually used, not a superset that exists on disk.
 *  - `name` — a rename must invalidate a stored precedent (plan §6.3 compares
 *    "the name it had at capture"). Without `name`, a rename is invisible here.
 *  - `label`, for the SAME reason on the `rel:` half, which the first cut of
 *    this module missed. A verb's label is not decoration: `resolveVerb`
 *    matches the bracket term against it in both the exact and the substring
 *    tier (server/cortex-resolve.ts:345, :350) and `bind` writes it into
 *    `operand.resolvedName`. So a label edit is resolution-affecting and is
 *    recorded in the AST — exactly the two properties that make node `name`
 *    load-bearing above. knowledge/ingest.mjs UPSERTs `label` from the checked-in
 *    SoT (knowledge/ontology/relation-types.json) on every run, so a re-ingest
 *    after an editorial label change could flip `rel:verb[…]` from a unique bind
 *    to `ambiguous_operand`, or leave a cached AST carrying a `resolvedName`
 *    that no longer exists, while the fingerprint stayed byte-identical and
 *    Wing's "ontologyVersion moved → revalidate" rule never fired.
 *  - `parentId` — a re-parent changes `node.path`, which `rebuildTaxonomyFts`
 *    indexes, which changes late-binding results. It is resolution-affecting.
 *  - `description` is deliberately EXCLUDED. K1 curated overrides
 *    (`applyDescriptionOverride`) churn editorially; invalidating every stored
 *    precedent on a wording fix costs more than it buys. Named, accepted cost: a
 *    description edit can shift an FTS ranking without moving the version. This
 *    is the one place the fingerprint is deliberately coarse.
 */
export function canonicalOntologyVocabulary(): string {
  const lines: string[] = [];

  for (const node of [...allNodes()].sort((a, b) => byCodeUnit(a.id, b.id))) {
    lines.push(['t', node.id, node.parentId ?? '-', node.name].join('\t'));
  }

  for (const row of [...db.listRelationTypes()]
    .filter((r) => isLiveVerbStatus(r.status))
    .sort((a, b) => byCodeUnit(a.type, b.type))) {
    lines.push(['r', row.type, row.status, row.label].join('\t'));
  }

  return lines.join('\n');
}

/**
 * `onto1:<first 16 hex of sha256(canonicalOntologyVocabulary())>`.
 *
 * DIVERGENCE from the spec's (non-normative) implementation note, which suggests
 * memoizing this in a module-level cache invalidated from `registerExtNode`,
 * `registerExtNodes`, `insertProposedRelationType`, `setRelationTypeStatus` and
 * `seedRelationTypes`. It is computed FRESH on every call instead, because:
 *
 *  1. Every one of those invalidation seams would require `server/taxonomy.ts`
 *     or `server/db.ts` — modules this one imports — to import this module back.
 *     That is a genuine import cycle through the esbuild bundle, not a style
 *     objection.
 *  2. A stale fingerprint is not a slow answer, it is a WRONG one: it asserts
 *     "the ontology did not move" to a dispatcher whose entire job is to notice
 *     that it did. The failure mode of a missed invalidation site is silent and
 *     is exactly the drift this field exists to catch.
 *  3. It is one string join per node plus one sha256, on a route that is not hot
 *     and that already does several COUNT(*) queries. MEASURED at 0.18 ms per
 *     call over the 806-node seed spine — cheaper than the census beside it.
 *     server/cortex-resolve.test.ts pins the order of magnitude so a future
 *     O(n²) regression cannot hide behind "it was never cached anyway".
 *
 * Boot-scoped, and correctly so: the in-memory tree is built once at boot, while
 * `knowledge/ingest.mjs` writes `taxonomy_nodes_ext` straight to the DB file and
 * relies on a restart. Between the two, `getNode` answers "unknown" for ids that
 * exist on disk — and the fingerprint describes the tree the VALIDATOR used,
 * which is the correct semantics: an AST records what it was checked against,
 * not what another process believes.
 */
export function cortexOntologyVersion(): string {
  const digest = createHash('sha256').update(canonicalOntologyVocabulary(), 'utf8').digest('hex');
  return `onto1:${digest.slice(0, 16)}`;
}
