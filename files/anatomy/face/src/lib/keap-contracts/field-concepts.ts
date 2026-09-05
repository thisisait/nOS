/**
 * VENDORED from thisisait/nos-keap at tag v1.44.0 (commit a97c91ff) — DO NOT
 * EDIT. A pinned snapshot of KEAP's DataTable schema: the authority the
 * schema-pin gate (schema-pin.test.ts) validates every state/keap-tables/
 * *.table.yml against, so "a definition runs ahead of the pin" is structurally
 * impossible rather than a matter of release discipline (cross-repo-contracts
 * clause 2; the caddy-sessions `style: chat` incident is what it prevents).
 *
 * Re-vendor ONLY when roles/pazny.keap keap_repo_ref bumps: re-run
 * tools/vendor-keap-contracts (or copy shared/contracts/{visibility,table,
 * field-concepts}.ts from the new tag). A hand-edit here forks the contract —
 * the exact drift the gate exists to catch.
 * Upstream: nos-keap shared/contracts/field-concepts.ts
 */
/**
 * Field concepts — L1 of the nOS genome: the common vocabulary for WHAT A
 * COLUMN MEANS.
 *
 * WHY THIS EXISTS. A DataTable column carries two machine facts today — `kind`
 * (how the value is stored) and `role` (how OLAP may aggregate it) — and zero
 * facts about its meaning. `status` in five different tables is five unrelated
 * strings; `taxonomy_ref`, `owner` and `slug` repeat across every seeded table
 * with nothing tying them together. Meaning lives only in the human-readable
 * `label`, which no consumer can compare.
 *
 * That is the "no common denominator" problem, stated for one organ. This file
 * is the denominator, and it is deliberately the SMALLEST thing that can be
 * one: a closed, versioned, git-owned vocabulary with a membership gate.
 *
 * WHAT IT HONESTLY DOES, so nobody over-claims it later:
 *   - it GATES: an unknown concept is refused at write time, so the set cannot
 *     silently grow by typo the way a free-text column would;
 *   - it makes columns COMPARABLE ACROSS TABLES — "every column meaning
 *     lifecycle.status" is a query for the first time;
 *   - it gives L2 (per-concept vector slots) something to hang off; the ids
 *     here are the stable anchor L2 needs and cannot invent later.
 *
 * WHAT IT DOES NOT DO: rendering `Label [concept]: value` into a row body does
 * NOT make embeddings concept-aware. One vector covers the whole body, which is
 * truncated before it is embedded, so a shared bracket token is a few tokens
 * diluted among thousands. It helps the lexical (BM25/FTS) leg, and that is the
 * whole of its retrieval claim until L2 lands.
 *
 * VOCABULARY DISCIPLINE. Ids are `namespace.name`. Additive-only: a concept may
 * be ADDED freely, but never removed or renamed, because a stored column may
 * reference it and there is no repair path for a stranded token. Retire by
 * marking `deprecated: true` and steering new declarations elsewhere.
 *
 * CROSS-REPO. nOS vendors this file verbatim (the `shared/contracts/cortex.ts`
 * precedent: provenance header + a vendoring gate that diffs the copies), so a
 * table definition authored in the nOS repo is validated against the same set
 * the KEAP server enforces.
 */
import { z } from 'zod';

/**
 * Deliberately NOT `import type { ColumnKind } from './table'` — table.ts
 * imports THIS file to build columnDefSchema, and a cycle between two modules
 * that both construct zod schemas at import time resolves to `undefined` on one
 * side depending on entry order. The dependency runs one way only; that every
 * `kinds` entry below is a real ColumnKind is asserted by
 * field-concepts.test.ts instead, which is where a cycle-free codebase pays for
 * the lost compile-time link.
 */
type ColumnKindName = string;

export interface FieldConcept {
  /** `namespace.name` — stable forever once published. */
  id: string;
  /** Human label for pickers and the concept catalog. */
  label: string;
  /** What a column carrying this concept holds. Read by operators AND agents. */
  description: string;
  /**
   * Column kinds this concept may bind to. A concept is a claim about meaning,
   * and a meaning implies a shape: `net.port` on a `text` column is a
   * declaration error, not a stylistic choice. Empty array = any kind.
   */
  kinds: ColumnKindName[];
  /** Steer new declarations away without stranding stored ones. */
  deprecated?: boolean;
}

/**
 * The vocabulary. Derived from the 76 columns of the five nOS-seeded tables —
 * every one of them binds, which is the point: these are not aspirational
 * categories, they are the meanings the estate already uses without naming.
 */
export const FIELD_CONCEPTS: FieldConcept[] = [
  // ── identity ────────────────────────────────────────────────────────────
  { id: 'identity.name', label: 'Name', kinds: ['text'], description: 'Human-facing display name of the thing the row describes.' },
  { id: 'identity.slug', label: 'Slug', kinds: ['text'], description: 'Stable machine identifier, unique within the table. Doubles as the row id when present.' },
  { id: 'identity.description', label: 'Description', kinds: ['text'], description: 'Prose summary of the row. The field intended for retrieval and embedding.' },
  { id: 'identity.version', label: 'Version', kinds: ['text'], description: 'Version string of the described artifact.' },

  // ── classification ──────────────────────────────────────────────────────
  { id: 'class.category', label: 'Category', kinds: ['text', 'select'], description: 'Open grouping — business capability, domain area. Not a closed enum.' },
  { id: 'class.kind', label: 'Kind', kinds: ['select', 'text'], description: 'Closed sub-type within this table’s own collection.' },
  { id: 'class.tenant', label: 'Tenant', kinds: ['text'], description: 'Owning tenant in a multi-tenant estate.' },
  { id: 'class.group', label: 'Group', kinds: ['text', 'select'], description: 'Deployment or organisational grouping (e.g. a compose stack).' },
  { id: 'class.complexity', label: 'Complexity tier', kinds: ['select', 'text'], description: 'Position on a build-complexity ladder (e.g. the face-app F1–F4/H tiers). Not an access tier.' },

  // ── lifecycle ───────────────────────────────────────────────────────────
  { id: 'lifecycle.status', label: 'Status', kinds: ['select', 'text'], description: 'Current operational state: draft / enabled / disabled / archived.' },
  { id: 'lifecycle.stage', label: 'Lifecycle stage', kinds: ['select'], description: 'Position on the plan → phase-in → active → phase-out → end-of-life arc.' },
  { id: 'lifecycle.criticality', label: 'Criticality', kinds: ['select'], description: 'Business criticality — how much breaks when this does.' },

  // ── access (the nOS genome access facet, per column) ─────────────────────
  { id: 'access.tier', label: 'Access tier', kinds: ['select', 'text'], description: 'RBAC tier required to reach the described thing.' },
  { id: 'access.sso_mode', label: 'SSO mode', kinds: ['select'], description: 'How identity reaches the service: native_oidc / header_oidc / forward_auth / none.' },
  { id: 'access.owner', label: 'Owner', kinds: ['user', 'text'], description: 'The principal accountable for the described thing.' },

  // ── addressing ──────────────────────────────────────────────────────────
  { id: 'net.domain', label: 'Domain', kinds: ['text'], description: 'Hostname the described thing answers on.' },
  { id: 'net.port', label: 'Port', kinds: ['number'], description: 'TCP port the described thing binds.' },
  { id: 'net.url', label: 'Entry URL', kinds: ['text'], description: 'Absolute URL where the described thing is reached by a user or client.' },
  // Split out of net.url the first time both were needed in one table: "where
  // it runs" and "where its source lives" are different meanings, and one
  // concept per table means the vocabulary has to say so.
  { id: 'net.repo', label: 'Repository', kinds: ['text'], description: 'Source repository URL for the described thing.' },
  { id: 'fs.path', label: 'Path', kinds: ['text'], description: 'Filesystem or VFS path, relative to a root the consumer knows.' },
  { id: 'deploy.image', label: 'Image', kinds: ['text'], description: 'Container image reference including tag.' },

  // ── presentation ────────────────────────────────────────────────────────
  { id: 'ui.icon', label: 'Icon', kinds: ['text'], description: 'Icon identifier or glyph for rendering the row.' },
  { id: 'ui.sort', label: 'Sort order', kinds: ['number'], description: 'Manual ordering weight within a rendered list or grid.' },
  { id: 'ui.pinned', label: 'Pinned', kinds: ['boolean'], description: 'Whether the row is surfaced in a primary place (desktop, favourites).' },
  { id: 'ui.embeddable', label: 'Embeddable', kinds: ['boolean'], description: 'Whether the described thing may be rendered inside an iframe/window.' },
  { id: 'ui.interactive', label: 'Has a UI', kinds: ['boolean'], description: 'Whether the described thing exposes a user interface at all. Distinct from embeddable: a UI may exist and still refuse framing.' },
  { id: 'ui.surface', label: 'Surface', kinds: ['select', 'text'], description: 'Which UI surface the row opens — an editor key, or a raw table.' },
  { id: 'ui.style', label: 'Style', kinds: ['text', 'json'], description: 'Visual styling payload (gradient, theme tokens) for the row.' },
  { id: 'ui.layout', label: 'Layout', kinds: ['json'], description: 'Structural layout description — cells, panes, grid placement.' },

  // ── graph ───────────────────────────────────────────────────────────────
  { id: 'graph.anchor', label: 'Taxonomy anchor', kinds: ['taxonomyRef'], description: 'The taxonomy node this row hangs from in the universe.' },
  { id: 'graph.depends_on', label: 'Depends on', kinds: ['json', 'objectRef', 'rowRef'], description: 'Things this row requires in order to function. A rowRef is the typed form; json is the pre-relations one.' },
  { id: 'graph.uses', label: 'Uses', kinds: ['json', 'objectRef', 'rowRef'], description: 'Components or organs this row consumes without strictly requiring.' },
  { id: 'graph.parent', label: 'Parent row', kinds: ['text', 'objectRef', 'rowRef'], description: 'The row this one nests under, making a table self-nesting. `rowRef` is the referential form and the one to use — this concept previously read "a slug today because there is no rowRef kind", and that kind now exists. `text` stays legal so every table written before it keeps validating.' },
  { id: 'graph.stores', label: 'Data stores', kinds: ['json', 'objectRef', 'rowRef'], description: 'Persistent stores this row reads from or writes to.' },


  // ── time ────────────────────────────────────────────────────────────────
  // The first concepts in this vocabulary that bind to `date`. Their absence
  // was measured, not assumed: the nOS roadmap table's own seeder carries the
  // note "KEAP has no concept that accepts kind: date (verified 2026-08-02 —
  // none of the 36)", so its timeline column shipped without a meaning.
  //
  // `target` and `occurred_at` are kept APART on purpose. One is an intention
  // and the other is a fact, and a table that stores both in one column can
  // never answer "did this land when we said it would".
  { id: 'time.target', label: 'Target date', kinds: ['date'], description: 'When the row is INTENDED to happen. A plan, revisable, and never evidence that anything occurred.' },
  { id: 'time.occurred_at', label: 'Occurred at', kinds: ['date'], description: 'When the thing actually happened, as distinct from when it was planned or when someone claimed it. Written from observation.' },
  { id: 'time.verified_at', label: 'Verified at', kinds: ['date'], description: 'When an independent check last looked at this row. Staleness here is itself information — an old date on a live claim.' },

  // ── evidence ────────────────────────────────────────────────────────────
  // A CLAIM AND AN OBSERVATION ARE DIFFERENT KINDS OF FACT, and this namespace
  // exists so a table can hold both without conflating them.
  //
  // The nOS estate paid for this repeatedly: a security queue reported fifteen
  // items pending while six were already live at their fixed version, because
  // its status was written by the process that filed the work rather than by
  // anything that looked; a backup reported success for six services whose
  // archives were empty for weeks. The shape is always a success marker
  // written by the code that attempted the work.
  //
  // So `lifecycle.status` stays what someone CLAIMS, and these three carry
  // what something OBSERVED. A row whose status says done and whose
  // verification says contradicted is the most useful row in any such table,
  // and it is unreachable in a design where one writer owns both.
  { id: 'evidence.verification', label: 'Verification', kinds: ['select'], description: 'What an INDEPENDENT check concluded about this row: unverified, confirmed, contradicted, unverifiable. Never written by whoever did the work.' },
  { id: 'evidence.method', label: 'Verified by', kinds: ['text'], description: 'What performed the check — a probe, a query, a gate. Names the instrument so a verdict can be re-taken or distrusted.' },
  { id: 'evidence.observation', label: 'Observation', kinds: ['json'], description: 'What the check actually saw, kept raw. Free-form because instruments differ; it is evidence, not a schema.' },

  // ── provenance & machine ────────────────────────────────────────────────
  { id: 'prov.generated_by', label: 'Generated by', kinds: ['text'], description: 'The agent, tool or human that produced this row.' },
  { id: 'prov.source', label: 'Source', kinds: ['select', 'text'], description: 'Which process put this row here — an operator, an agent observation, a scanner, a review. Determines what the row must satisfy before it is trusted.' },
  { id: 'prov.ref', label: 'Source reference', kinds: ['text'], description: 'Identifier of this row within its source system, so the original record can be found again.' },
  { id: 'prov.references', label: 'References', kinds: ['json'], description: 'Outbound links this row cites — plan document, workflow run, release tag, commit. A dict because the useful set keeps growing.' },
  { id: 'prov.system', label: 'System-owned', kinds: ['boolean'], description: 'True when the row is repo-seeded and must survive a user reset.' },
  { id: 'machine.embedding', label: 'Embedding', kinds: ['vector'], description: 'Machine-generated vector of another column. Never authored by hand.' },
  { id: 'ref.table', label: 'Table reference', kinds: ['text'], description: 'Slug of another DataTable this row points at.' },
];

export const FIELD_CONCEPT_BY_ID: ReadonlyMap<string, FieldConcept> = new Map(
  FIELD_CONCEPTS.map((c) => [c.id, c]),
);

/** `namespace.name`, lowercase. Shape-checked separately from membership so a
 *  malformed id and an unknown-but-well-formed id give different errors. */
export const FIELD_CONCEPT_ID = /^[a-z][a-z0-9]*(\.[a-z][a-z0-9_]*)+$/;

export const fieldConceptSchema = z
  .string()
  .regex(FIELD_CONCEPT_ID, 'concept must be namespace.name in lowercase')
  .refine((v) => FIELD_CONCEPT_BY_ID.has(v), {
    message: 'unknown field concept (the vocabulary is closed — add it to shared/contracts/field-concepts.ts first)',
  });

/** Membership + shape gate for one declaration. Returns an error string, or
 *  null when the pair is legal. Kept separate from the zod schema because the
 *  kind is only known alongside the column, not on the concept string alone. */
export function checkConceptBinding(concept: string, kind: ColumnKindName): string | null {
  const c = FIELD_CONCEPT_BY_ID.get(concept);
  if (!c) return `unknown field concept: ${concept}`;
  if (c.kinds.length && !c.kinds.includes(kind)) {
    return `concept ${concept} may not bind a ${kind} column (allowed: ${c.kinds.join(', ')})`;
  }
  return null;
}
