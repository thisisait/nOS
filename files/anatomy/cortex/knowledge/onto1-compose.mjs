/**
 * REFERENCE IMPLEMENTATION of the `onto1:` composition contract.
 *
 * P-2 of the cortex backend/UI split. `ast.binding.ontologyVersion` is what tells
 * a dispatcher "the ontology moved, revalidate". If KEAP and the nOS cortex organ
 * compose the same git data differently, they produce different fingerprints from
 * identical input — and then each side rejects the other's ASTs while both
 * believe they are correct. That failure is silent and total, so the composition
 * cannot stay "whatever server/taxonomy.ts happens to do".
 *
 * This module is that behaviour written down as executable data-in/data-out, with
 * no dependency on the server, the database, or TypeScript. It is deliberately a
 * SECOND implementation: `knowledge/onto1-conformance.mjs` grades a port against
 * the fixtures, and `server/onto1-agreement.test.ts` asserts KEAP's own runtime
 * agrees with this one over the REAL tree. Two independent implementations
 * agreeing on 1800+ live nodes is a far stronger equivalence proof than either
 * agreeing with a toy fixture.
 *
 * Normative prose: docs/specs/onto1-composition-contract.md
 */
import { createHash } from 'node:crypto';

/** §2.1 — a user-defined taxonomy ROOT is one bare lowercase slug. Seed domains
 *  are two-digit numerals, so the two id spaces are structurally disjoint. */
export const USER_ROOT_RE = /^[a-z][a-z0-9-]*$/;

/** §2.2 — the fixpoint bound. Reached only by a cycle or an unreachable parent. */
export const MAX_REGISTRATION_PASSES = 12;

/** §3.1 — ordering is by UTF-16 code unit, NOT localeCompare. `'01.1' < '01.10'`
 *  and any locale-aware collation will disagree on some real id. */
export function byCodeUnit(a, b) {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** §4.1 — a verb counts toward the vocabulary iff its status is live.
 *  `'proposed'` is excluded: any RW bearer can plant one. */
export function isLiveVerbStatus(status) {
  return status === 'seed' || status === 'confirmed';
}

/**
 * §2 — compose the node set.
 *
 * @param spine  Array of `{ key, category }` domain documents, IN DOMAIN ORDER
 *               (knowledge/spine/*.json read in file-name order).
 * @param extRows Array of `{ id, parentId, name }` grown rows (taxonomy_nodes_ext).
 *               `parentId` '' (or null) marks a user root.
 * @returns Map id → { id, parentId, name, ext } — insertion-ordered, which the
 *          fingerprint does not depend on (it sorts) but the UI does.
 */
export function composeNodes(spine, extRows) {
  const nodes = new Map();

  // §2.1 — the spine, depth-first, in domain order. parentId comes from NESTING,
  // never from parsing the id: the two agree today (lint gates it) but the
  // composition is defined by structure, so a future id scheme cannot silently
  // reparent the tree.
  const walk = (node, parentId) => {
    nodes.set(node.id, { id: node.id, parentId, name: node.name, ext: false });
    for (const sub of Object.values(node.subcategories ?? {})) walk(sub, node.id);
    for (const item of node.items ?? []) walk(item, node.id);
  };
  for (const doc of spine) walk(doc.category, null);

  // §2.2 — grown rows, as a FIXPOINT rather than one pass. A row registers only
  // once its parent is present, so a subtree that arrives children-first still
  // lands; without this a whole tree could be dropped in silence because its
  // rows happened to be ordered by created_at rather than by ancestry.
  const pending = extRows.map((r) => ({ ...r, parentId: r.parentId ?? '' }));
  for (let pass = 0; pass < MAX_REGISTRATION_PASSES && pending.length; pass++) {
    const before = pending.length;
    for (let i = pending.length - 1; i >= 0; i--) {
      const row = pending[i];
      // §2.3 — an id already present WINS and the row is consumed, not dropped.
      // The spine is authoritative over a grown row of the same id.
      if (nodes.has(row.id)) { pending.splice(i, 1); continue; }
      const isRoot = !row.parentId;
      // §2.4 — a parentless row is a root ONLY inside the slug shape. Otherwise
      // it is indistinguishable from a row whose parent failed to resolve, which
      // is the silent-orphan case the parent check exists to catch.
      if (isRoot && !USER_ROOT_RE.test(row.id)) continue;
      if (!isRoot && !nodes.has(row.parentId)) continue;
      nodes.set(row.id, { id: row.id, parentId: isRoot ? null : row.parentId, name: row.name, ext: true });
      pending.splice(i, 1);
    }
    if (pending.length === before) break; // no progress — the rest are unregisterable
  }

  return { nodes, dropped: pending.map((r) => r.id) };
}

/**
 * §3–§4 — the canonical serialization.
 *
 * Two record kinds, each a tab-joined line, joined by '\n' with NO trailing
 * newline:
 *   t \t <id> \t <parentId | "-"> \t <name>        every composed node, id ASC
 *   r \t <type> \t <status> \t <label>             every LIVE verb, type ASC
 */
export function canonicalVocabulary(nodes, relationTypes) {
  const lines = [];
  for (const node of [...nodes.values()].sort((a, b) => byCodeUnit(a.id, b.id))) {
    lines.push(['t', node.id, node.parentId ?? '-', node.name].join('\t'));
  }
  for (const row of [...relationTypes]
    .filter((r) => isLiveVerbStatus(r.status))
    .sort((a, b) => byCodeUnit(a.type, b.type))) {
    lines.push(['r', row.type, row.status, row.label].join('\t'));
  }
  return lines.join('\n');
}

/** §5 — `onto1:` + the first 16 hex of sha256 over the UTF-8 serialization. */
export function onto1(canonical) {
  return `onto1:${createHash('sha256').update(canonical, 'utf8').digest('hex').slice(0, 16)}`;
}

/** Convenience: spine + ext rows + verbs → { canonical, onto1, nodeCount, dropped }. */
export function composeFingerprint(spine, extRows, relationTypes) {
  const { nodes, dropped } = composeNodes(spine, extRows);
  const canonical = canonicalVocabulary(nodes, relationTypes);
  return { canonical, onto1: onto1(canonical), nodeCount: nodes.size, dropped };
}
