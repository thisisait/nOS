/**
 * Shared ontology-SoT vocabulary for dump / ingest / lint / roundtrip.
 *
 * The ONTOLOGY layer is the R3 store: the controlled verb registry
 * (`relation_types`) and the moderated typed edges (`relations`). Unlike the
 * taxonomy delta, it had NO git source of truth until now — it lived only in the
 * container volume, so the 2026-07-22 data-dir reset silently took the whole
 * moderated set with it and nothing noticed for two days.
 *
 * These four scripts each need to agree on exactly one thing — WHICH FILE OWNS A
 * GIVEN EDGE — because ingest's reset scope is "delete what this file owns, then
 * insert what it carries". If dump and ingest disagreed about ownership by even
 * one row, ingest would either orphan rows (dump wrote them to file A, ingest
 * resets file B) or double-delete a sibling's freshly-inserted edges. That is the
 * same class of bug the canonical importer guards with its per-domain wipe scope;
 * here the partition key is not derivable in SQL, so it is computed in JS from
 * this ONE definition and imported everywhere.
 */

/** Stable L0 spine → folder slug. Mirrors dump.mjs's canonical layout so an
 *  ontology partition file sits under a name a reviewer already recognises. */
export const L0_DIR = {
  '01': '01-natural-sciences',
  '02': '02-formal-sciences',
  '03': '03-applied-sciences-technology',
  '04': '04-social-sciences',
  '05': '05-humanities',
  '06': '06-arts-creative-expression',
  '07': '07-practical-skills-trades',
  '08': '08-survival-emergency-preparedness',
  '09': '09-reference-documentation',
  '10': '10-cultural-preservation',
  '11': '11-digital-preservation',
  '12': '12-post-disaster-rebuilding',
};

export const l0 = (id) => String(id).split('.')[0];
export const l1 = (id) => String(id).split('.').slice(0, 2).join('.');

/** Where edges with no taxonomy endpoint land. R3's cross-kind guard makes those
 *  impossible today (every derived edge is node↔object), but `source='manual'`
 *  has no such guard, and a partitioner that throws on an input the schema
 *  permits is a landmine — it would fail the ingest of a perfectly legal row. */
export const OBJECT_PARTITION = '_objects';

export const ONTOLOGY_DIR = 'ontology';
export const RELATIONS_SUBDIR = 'relations';
export const TYPES_FILE = 'relation-types.json';

export const VALID_KINDS = new Set(['node', 'object']);
export const VALID_STATUS = new Set(['proposed', 'confirmed', 'rejected']);
export const VALID_TYPE_STATUS = new Set(['seed', 'proposed', 'confirmed']);
/** 'toe' is deliberately absent: those rows are a BOOT MIRROR of
 *  concept_relations, which the canonical files already version. Dumping them
 *  here would version the same edges twice and let the two copies drift. */
export const VALID_SOURCES = new Set(['derived', 'manual']);

/**
 * The partition a relation belongs to — the L0 of its taxonomy endpoint.
 *
 * Accepts both shapes so callers never have to translate: DB rows
 * (`from_ref`/`from_kind`, snake_case) and canonical file records
 * (`from`/`fromKind`, camelCase).
 */
export function relationPartition(r) {
  const fromRef = r.from_ref ?? r.from;
  const toRef = r.to_ref ?? r.to;
  const fromKind = r.from_kind ?? r.fromKind ?? 'node';
  const toKind = r.to_kind ?? r.toKind ?? 'node';
  // `from` wins when both endpoints are taxonomy nodes, so the choice is
  // deterministic rather than dependent on column order.
  const nodeRef = fromKind === 'node' ? fromRef : toKind === 'node' ? toRef : null;
  if (!nodeRef) return OBJECT_PARTITION;
  const top = l0(nodeRef);
  return L0_DIR[top] || top;
}

/** Identity of an edge in the store: the UNIQUE(from_ref, to_ref, type) key.
 *  Used for sorting, dedupe detection and file↔DB comparison. */
export function relationKey(r) {
  const fromRef = r.from_ref ?? r.from;
  const toRef = r.to_ref ?? r.to;
  return `${fromRef}|${toRef}|${r.type}`;
}

/** Deterministic row id — byte-identical to server/db.ts `relationId()`. Ingest
 *  MUST reproduce it: the server upserts on this id, so a divergent derivation
 *  here would insert a duplicate row the app then treats as a second edge. */
export function relationId(fromRef, toRef, type, createHash) {
  return `r-${createHash('sha1').update(`${fromRef} ${toRef} ${type}`).digest('hex').slice(0, 16)}`;
}

/** Canonical file record for one relation row (DB → file). Optional fields are
 *  OMITTED rather than emitted as null, so a hand-written file that leaves them
 *  out round-trips byte-identically instead of gaining `"model": null` noise. */
export function toFileRecord(row) {
  const rec = {
    from: row.from_ref,
    fromKind: row.from_kind,
    to: row.to_ref,
    toKind: row.to_kind,
    type: row.type,
    source: row.source,
    status: row.status,
  };
  if (row.confidence !== null && row.confidence !== undefined) rec.confidence = row.confidence;
  if (row.justification) rec.justification = row.justification;
  if (row.model) rec.model = row.model;
  // Provenance timestamp is kept, not regenerated: "when was this edge typed"
  // is part of the moderation record, and silently resetting it on every
  // rebuild is exactly the slow degradation this SoT exists to stop.
  if (row.created_at !== null && row.created_at !== undefined) rec.createdAt = row.created_at;
  return rec;
}

/** Stable order for a partition file: by (from, to, type). Keeps git diffs to
 *  the rows that actually changed. */
export function sortRelations(list) {
  return list.sort((a, b) => relationKey(a).localeCompare(relationKey(b)));
}

/** File name for a partition (flat under ontology/relations/). */
export const partitionFile = (partition) => `${partition}.json`;
