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
 * Upstream: nos-keap shared/contracts/table.ts
 */
/**
 * Data-table contract — the shape every TableStore driver speaks (Track R2′,
 * owner direction 2026-07-12: "DataTable(Store) je klíčový — musí být dost
 * abstraktní").
 *
 * Design pillars:
 *  - COLUMN KINDS cover rich values: files arrive BY REFERENCE (same doctrine
 *    as intake media), vectors are first-class (libSQL F32 heritage),
 *    taxonomyRef/objectRef wire rows into the knowledge graph.
 *  - OLAP IN THE DNA: every column carries a `role` (dimension | measure |
 *    attribute) and the query surface includes `AggregateQuery` (group-by
 *    dimensions × aggregated measures) — a SharePoint-list today, a cube
 *    tomorrow (the DuckDB/parquet driver inherits the same contract).
 *  - CAPABILITIES, not assumptions: drivers declare what they can do
 *    (transactions, rowHistory, aggregate, vectorColumns, objectVersioning,
 *    events); the UI renders only what the chosen storage offers.
 *
 * Shared between server drivers, the web UI grid, and the extension.
 */
import { z } from 'zod';
import { checkConceptBinding, fieldConceptSchema } from './field-concepts';
import { tableVisibilitySchema, sharedWithSchema, type ShareEntry, type RowSharing } from './visibility';

// ── Columns ───────────────────────────────────────────────────────────────────

export const columnKindSchema = z.enum([
  'text',
  'number',
  'boolean',
  'date', // epoch seconds
  'select', // one of options
  'json', // free structured payload
  'file', // BY REFERENCE: { url, mime?, name?, size? }
  'vector', // number[] of fixed dim
  'taxonomyRef', // node id — anchors the ROW into the universe
  'objectRef', // knowledge_object id
  'rowRef', // row id in ANOTHER table — the structural join (see below)
  'user', // KEAP user id (attribution columns)
]);
export type ColumnKind = z.infer<typeof columnKindSchema>;

/** OLAP role: dimensions slice, measures aggregate, attributes just describe. */
export const columnRoleSchema = z.enum(['dimension', 'measure', 'attribute']);
export type ColumnRole = z.infer<typeof columnRoleSchema>;

export const columnDefSchema = z.object({
  key: z
    .string()
    .min(1)
    .max(64)
    .regex(/^[a-z][a-z0-9_]*$/, 'snake_case keys only'),
  label: z.string().min(1).max(120),
  kind: columnKindSchema,
  role: columnRoleSchema.default('attribute'),
  required: z.boolean().default(false),
  /** select: allowed values */
  options: z.array(z.string()).max(200).optional(),
  /** vector: dimension (validated on write) */
  dim: z.number().int().positive().max(4096).optional(),
  /** measure display/aggregation hint, e.g. "kg", "CZK" */
  unit: z.string().max(24).optional(),

  /**
   * L1 field concept — WHAT this column means, from the closed vocabulary in
   * field-concepts.ts. Optional so every table that exists today stays valid
   * byte-for-byte; when present it is gated on membership here and on
   * concept↔kind compatibility in `validateColumnConcepts` below.
   */
  concept: fieldConceptSchema.optional(),


  // ── rowRef: the structural join ────────────────────────────────────────────
  // `taxonomyRef` and `objectRef` anchor a row into the universe; NEITHER points
  // at another ROW, so before this kind existed an invoice could not reference
  // its customer and DataTables was an entity registry with no edges.
  //
  // The stored value is the target's row id as a plain string — NOT a
  // {table,row} pair. The target table is declared ONCE here, so a per-row
  // target could disagree with the schema, and a join whose target varies by row
  // is not a join.
  //
  // CARDINALITY IS EXPRESSED BY PLACEMENT, not by a new kind:
  //   1:N  put the rowRef on the MANY side (invoice.customer -> party)
  //   N:N  a junction table with TWO rowRef columns
  // There is deliberately no array-of-refs kind: an N:N edge almost always
  // carries its own attributes (role, share, validity), an array cell has
  // nowhere to put them, `AggregateQuery` cannot group by an array without an
  // unnest operator this contract does not have, and row history is per row so
  // membership changes would degrade to a JSON blob diff.

  /** rowRef: id of the table this column points into. REQUIRED for kind 'rowRef'. */
  refTable: z.string().min(1).max(128).optional(),
  /** rowRef: column key IN THE TARGET used as the human label (picker + chip). */
  refDisplay: z.string().max(64).optional(),
  /**
   * rowRef: what happens to referencing rows when the target row is deleted.
   * 'restrict' is the default on purpose — an orphaned invoice line is a data
   * defect, not a tidy-up. Enforcement is the store's job; this declares intent.
   */
  onDelete: z.enum(['restrict', 'setNull', 'cascade']).default('restrict'),
});
export type ColumnDef = z.infer<typeof columnDefSchema>;

/**
 * Concept↔kind compatibility, plus the one-concept-per-table rule.
 *
 * A concept names a meaning, and a meaning is singular within a collection: two
 * columns both claiming `lifecycle.status` makes "the status of this row"
 * ambiguous for every consumer that queries by concept, which is the entire
 * reason concepts exist. Different tables reusing the same concept is the point
 * and stays legal.
 *
 * Returns error strings; empty array = valid.
 */
export function validateColumnConcepts(
  // Optional key/kind because zod hands superRefine the pre-default INPUT
  // shape, where every field with a `.default()` reads as optional.
  columns: Array<{ key?: string; kind?: string; concept?: string }>,
): string[] {
  const errors: string[] = [];
  const seen = new Map<string, string>();
  for (const c of columns) {
    if (!c.concept) continue;
    const bindErr = checkConceptBinding(c.concept, c.kind ?? '');
    if (bindErr) errors.push(`${c.key}: ${bindErr}`);
    const prior = seen.get(c.concept);
    if (prior) errors.push(`${c.key}: concept ${c.concept} is already declared by column ${prior}`);
    else seen.set(c.concept, c.key ?? '(unnamed)');
  }
  return errors;
}


export const tableSchemaSchema = z
  .object({
    columns: z.array(columnDefSchema).min(1).max(120),
  })
  .superRefine((val, ctx) => {

    for (const message of validateColumnConcepts(val.columns)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message, path: ['columns'] });
    }
    val.columns.forEach((c, i) => {
      // A rowRef with no target is not a weak join, it is an unresolvable one:
      // nothing downstream (picker, expand, back-reference index, graph edge)
      // can act on it, and it would be stored as an opaque string forever.
      if (c.kind === 'rowRef' && !c.refTable) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `column '${c.key}' is a rowRef and must declare refTable`,
          path: ['columns', i, 'refTable'],
        });
      }
      if (c.kind !== 'rowRef' && c.refTable !== undefined) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `column '${c.key}' declares refTable but its kind is '${c.kind}', not 'rowRef'`,
          path: ['columns', i, 'refTable'],
        });
      }
    });
  });
export type TableSchema = z.infer<typeof tableSchemaSchema>;

// ── Values ────────────────────────────────────────────────────────────────────

export const fileValueSchema = z.object({
  url: z.string().min(1),
  mime: z.string().max(120).optional(),
  name: z.string().max(240).optional(),
  size: z.number().int().nonnegative().optional(),
});
export type FileValue = z.infer<typeof fileValueSchema>;

/** Runtime validation of one row's values against a schema. */
export function validateRowValues(
  schema: TableSchema,
  values: Record<string, unknown>,
): string[] {
  const errors: string[] = [];
  const byKey = new Map(schema.columns.map((c) => [c.key, c]));
  for (const key of Object.keys(values)) {
    if (!byKey.has(key)) errors.push(`unknown column: ${key}`);
  }
  for (const col of schema.columns) {
    const v = values[col.key];
    if (v === undefined || v === null) {
      if (col.required) errors.push(`missing required column: ${col.key}`);
      continue;
    }
    switch (col.kind) {
      case 'text':
        if (typeof v !== 'string') errors.push(`${col.key}: expected string`);
        break;
      case 'number':
        if (typeof v !== 'number' || Number.isNaN(v)) errors.push(`${col.key}: expected number`);
        break;
      case 'boolean':
        if (typeof v !== 'boolean') errors.push(`${col.key}: expected boolean`);
        break;
      case 'date':
        if (typeof v !== 'number') errors.push(`${col.key}: expected epoch seconds`);
        break;
      case 'select':
        if (typeof v !== 'string' || (col.options && !col.options.includes(v)))
          errors.push(`${col.key}: expected one of options`);
        break;
      case 'json':
        if (typeof v !== 'object') errors.push(`${col.key}: expected object/array`);
        break;
      case 'file':
        if (!fileValueSchema.safeParse(v).success)
          errors.push(`${col.key}: expected file ref { url, mime?, name?, size? }`);
        break;
      case 'vector':
        if (!Array.isArray(v) || v.some((x) => typeof x !== 'number'))
          errors.push(`${col.key}: expected number[]`);
        else if (col.dim && v.length !== col.dim)
          errors.push(`${col.key}: expected dim ${col.dim}, got ${v.length}`);
        break;
      case 'taxonomyRef':
      case 'objectRef':
      case 'user':
        if (typeof v !== 'string') errors.push(`${col.key}: expected id string`);
        break;
      case 'rowRef':
        // Shape only. Whether the target row EXISTS — and whether the writer is
        // allowed to know that — is decided by the store, which can see the
        // other table. Answering existence here would turn a write into an
        // enumeration oracle for a table the caller may not read.
        //
        // An EMPTY string is accepted, and means "no reference". A cleared form
        // field arrives as "", and a first draft that rejected it left an
        // optional reference with no way to unset it — the store had to be
        // patched with an explicit null by every client, while `text` in the
        // same row accepted "" happily. The mirror already treats blank as an
        // absent edge, so nothing dangles.
        if (typeof v !== 'string') errors.push(`${col.key}: expected a row id string`);
        break;
    }
  }
  return errors;
}

// ── Query surface ─────────────────────────────────────────────────────────────

export const filterOpSchema = z.enum(['eq', 'neq', 'lt', 'lte', 'gt', 'gte', 'contains']);

export const rowFilterSchema = z.object({
  column: z.string(),
  op: filterOpSchema,
  value: z.union([z.string(), z.number(), z.boolean()]),
});
export type RowFilter = z.infer<typeof rowFilterSchema>;

export const listRowsQuerySchema = z.object({
  filter: z.array(rowFilterSchema).max(16).default([]),
  sort: z.object({ column: z.string(), dir: z.enum(['asc', 'desc']) }).optional(),
  cursor: z.string().optional(),
  limit: z.number().int().positive().max(500).default(50),
  /**
   * rowRef column keys to resolve into the target row's values. ONE LEVEL ONLY
   * and capped at 4 — an unbounded expansion over a self-referencing table
   * (a party owning a party) walks the cycle until something gives, and the
   * caller cannot see the depth it is asking for. Cycles are allowed and useful;
   * it is the expansion that must be bounded, not the schema.
   */
  expand: z.array(z.string()).max(4).default([]),
});
export type ListRowsQuery = z.infer<typeof listRowsQuerySchema>;

export const aggregateFnSchema = z.enum(['count', 'sum', 'avg', 'min', 'max']);

/** The OLAP slice: GROUP BY dimensions, aggregate measures. */
export const aggregateQuerySchema = z.object({
  dimensions: z.array(z.string()).max(6).default([]),
  measures: z
    .array(z.object({ column: z.string(), fn: aggregateFnSchema }))
    .min(1)
    .max(12),
  filter: z.array(rowFilterSchema).max(16).default([]),
  limit: z.number().int().positive().max(1000).default(200),
});
export type AggregateQuery = z.infer<typeof aggregateQuerySchema>;

// ── Driver capabilities & registry shapes ─────────────────────────────────────

export interface TableCapabilities {
  transactions: boolean;
  rowHistory: boolean;
  aggregate: boolean;
  vectorColumns: boolean;
  objectVersioning: boolean;
  events: boolean;
  /**
   * Can this driver resolve `rowRef` — expand on read, and answer "what points
   * at this row". Declared rather than assumed, per the contract's existing
   * pillar: the UI renders a picker and a back-reference panel only where the
   * chosen storage can actually serve them. A cross-driver reference (a libsql
   * table pointing into a postgres one) is NOT integrity-enforced by anybody,
   * so a driver may accept rowRef columns and still answer false here.
   */
  joins: boolean;
}

export const tableDriverSchema = z.enum(['libsql', 'rustfs', 'postgres', 'grist']);
export type TableDriver = z.infer<typeof tableDriverSchema>;

// Share scope — re-exported from the ONE ladder source (dtt-share-model).
// See shared/contracts/visibility.ts for the full grade ladder, principals
// and the shared_with ACL shapes; server/rbac.ts enforces the same ranks.
export { tableVisibilitySchema, type TableVisibilityContract } from './visibility';

// ── Graph-render metadata (S2⁶) ──────────────────────────────────────────────
// A table declares how it projects into the /explore universe. ABSENT → today's
// card-only behaviour, byte-identical (§3). Stored verbatim in the card
// `frontmatter.graph` by syncCard; read by server/graph.ts at render.

// Celestial form vocabulary — a zod mirror of asset-types.ts CelestialForm /
// orbital.ts (KEEP IN SYNC: the values byte-match server/asset-types.ts:21).
export const celestialFormSchema = z.enum(['planet', 'moon', 'asteroid', 'comet', 'station']);
export type CelestialFormContract = z.infer<typeof celestialFormSchema>;

// lowercase-kebab slug — mirrors the R3 verb convention (node-kind + edge type).
const kebabSlugSchema = z
  .string()
  .regex(/^[a-z][a-z0-9-]{0,63}$/, 'must be a lowercase-kebab slug');

export const graphMetaSchema = z.object({
  // Projection mode. 'card' (default) = one table-<slug> card, as today.
  // 'rows' = ALSO project each row as its own node (materialised in Stage 2;
  // Stage 1 ACCEPTS the value but renders CARD-ONLY — see server/graph.ts).
  mode: z.enum(['card', 'rows']).default('card'),

  // CARD visual override (independent of mode; lets a table pick its own look
  // instead of the generic asteroid/hue-180). Implemented in Stage 1.
  card: z
    .object({
      form: celestialFormSchema.optional(),
      hue: z.number().min(0).max(360).optional(),
      glyph: z.string().max(64).optional(),
    })
    .optional(),

  // Per-row node projection. Required when mode==='rows'. DEFINED here so the
  // contract is visible/stable, but Stage 1 does NOT materialise rows.
  node: z
    .object({
      idColumn: z.string().optional(), // column → stable node id; default: row uuid
      labelColumn: z.string(), // column → node label (required)
      kind: kebabSlugSchema.default('record'), // node-kind → legend + default visual
      form: celestialFormSchema.optional(),
      hue: z.number().min(0).max(360).optional(),
      glyph: z.string().max(64).optional(),
      anchorColumn: z.string().optional(), // a taxonomyRef column → the star this row orbits
    })
    .optional(),

  // Edge definitions: a column whose cell value points at another graph node.
  edges: z
    .array(
      z.object({
        column: z.string(), // an objectRef | taxonomyRef | rowRef column
        // 'row' resolves the cell against ANOTHER TABLE's row. It ships with the
        // rowRef column kind on purpose: a join that exists in the store but has
        // no edge kind is invisible in /explore, which is the same gap one layer
        // down that rowRef itself closes.
        toKind: z.enum(['node', 'object', 'row']),
        type: kebabSlugSchema.optional(), // edge label / relation verb
        label: z.string().max(120).optional(), // display label override
      }),
    )
    .max(8)
    .default([]),
});
export type GraphMeta = z.infer<typeof graphMetaSchema>;

// ── Render metadata (face DataTable surfaces) ────────────────────────────────
// A table declares HOW it wants to be rendered. ABSENT → the grid, byte-identical
// to today. Stored verbatim in the card `frontmatter.view` by syncCard, read by
// the nOS face BFF.
//
// WHY IT LIVES ON THE TABLE and not in the face: the answer to "is this a
// spreadsheet or an article list" is a property of the DATA, not of one client.
// A grid with `white-space: nowrap` is unusable for a table whose `research`
// column holds three paragraphs — and that is knowable from the table, once,
// rather than re-decided by every surface that renders it.

// `chat` (2026-09-01): one row is one EXCHANGE — what was asked, what came
// back. Added for nOS's caddy-sessions table, whose rows are turns; the face
// renders it and this enum was what refused it, so the view block sat authored
// half-way for a day. The style adds no capability: it names two existing
// columns, exactly as `blog` and `timeline` do.
export const tableViewStyleSchema = z.enum(['grid', 'blog', 'timeline', 'tiles', 'chat']);
export type TableViewStyle = z.infer<typeof tableViewStyleSchema>;

/**
 * A named class of rows worth jumping to, and a suggestion attached to one.
 *
 * The predicate shape is `rowFilterSchema` — the SAME vocabulary a query uses,
 * reused rather than re-spelled, so "status eq shipped" means one thing in this
 * repo. A second spelling of a comparison is how two answers to one question
 * start.
 *
 * `offer.action` is an ID FROM THE RENDERING CLIENT'S OWN CATALOG, never a
 * command, URL or handler, and KEAP deliberately does NOT validate its
 * membership: the catalog is per-runtime code (the face has one, a native
 * renderer would have its own), and a store that pinned the list would be
 * declaring a capability on behalf of a client it cannot see. The client
 * refuses an id it does not implement — fail-closed at the only place that
 * knows.
 */
export const rowPredicateSchema = rowFilterSchema;

export const highlightSpecSchema = z.object({
  label: z.string().min(1).max(48),
  when: z.array(rowPredicateSchema).min(1).max(4),
});

export const offerSpecSchema = z.object({
  label: z.string().min(1).max(120),
  action: z.string().min(1).max(48),
  /** REQUIRED, unlike a highlight's — an offer that is always on is a button. */
  when: z.array(rowPredicateSchema).min(1).max(4),
});

export const viewMetaSchema = z.object({
  style: tableViewStyleSchema.default('grid'),
  /** Row heading. Defaults to the first text column at render time. */
  titleColumn: z.string().optional(),
  /** The long-form cell: rendered as a paragraph block, never a table cell. */
  bodyColumn: z.string().optional(),
  /** Chronological ordering + the timeline gutter label. */
  dateColumn: z.string().optional(),
  /** Tile artwork — a `file` column, or text holding a URL/icon name. */
  mediaColumn: z.string().optional(),
  /** `chat` only: the column holding what was ASKED. `bodyColumn` holds the
   *  answer, so one row renders as a two-part exchange rather than a cell. */
  askColumn: z.string().optional(),
  /** Small facts shown beside the heading (status, tags, owner …). */
  metaColumns: z.array(z.string()).max(4).default([]),
  /**
   * The generative-UI seam (2026-08-28). All three name COLUMN KEYS, COMPARISON
   * OPS AND LABELS — nothing about chips, tabs, pixels or DOM — which is what
   * lets one declaration serve the Svelte face today and a native renderer
   * later, both reading it from `GET /agent/v1/tables/:slug`.
   *
   * They are filled by an author today and may be filled by a model tomorrow.
   * That is exactly why the columns they name are validated HERE, at author
   * time, on top of whatever narrowing the client does at render time: a block
   * is written once and rendered on every surface, so the check that catches a
   * name belongs where the name is written.
   */
  /** ≤2 column keys, outer→inner filter levels. A renderer affording only one
   *  honours `facets[0]`; "two levels" is the length, not a nested structure. */
  facets: z.array(z.string()).max(2).optional(),
  highlights: z.array(highlightSpecSchema).max(4).optional(),
  offer: offerSpecSchema.optional(),
});
export type ViewMeta = z.infer<typeof viewMetaSchema>;

/**
 * Validate a view block against the schema it will render. Returns error
 * strings; empty = valid.
 *
 * Each style has ONE column it cannot work without, and a missing one is an
 * authoring error rather than something to paper over at render time: a
 * timeline with no date column is a list in arbitrary order wearing a
 * timeline's clothes, which is worse than the grid it replaced.
 */
export function validateViewMeta(
  view: {
    style?: string;
    titleColumn?: string;
    bodyColumn?: string;
    dateColumn?: string;
    mediaColumn?: string;
    askColumn?: string;
    metaColumns?: string[];
    facets?: string[];
    highlights?: Array<{ label?: string; when?: Array<{ column?: string }> }>;
    offer?: { label?: string; action?: string; when?: Array<{ column?: string }> };
  },
  columns: Array<{ key?: string; kind?: string }>,
): string[] {
  const errors: string[] = [];
  const byKey = new Map(columns.filter((c) => c.key).map((c) => [c.key as string, c]));
  const need = (col: string | undefined, field: string) => {
    if (col === undefined) return;
    if (!byKey.has(col)) errors.push(`view.${field} references unknown column: ${col}`);
  };
  need(view.titleColumn, 'titleColumn');
  need(view.bodyColumn, 'bodyColumn');
  need(view.dateColumn, 'dateColumn');
  need(view.mediaColumn, 'mediaColumn');
  need(view.askColumn, 'askColumn');
  (view.metaColumns ?? []).forEach((c, i) => need(c, `metaColumns[${i}]`));
  (view.facets ?? []).forEach((c, i) => need(c, `facets[${i}]`));
  (view.highlights ?? []).forEach((h, i) =>
    (h.when ?? []).forEach((p, j) => need(p.column, `highlights[${i}].when[${j}].column`)),
  );
  (view.offer?.when ?? []).forEach((p, j) => need(p.column, `offer.when[${j}].column`));

  // A facet over a free-text or long-form column is not a filter, it is a list
  // of every distinct value in the table. The kinds below are the ones that
  // hold a bounded vocabulary; `text` is permitted because the roadmap's
  // `track` is one and a `select` was not available when it was authored.
  const FACETABLE = ['select', 'text', 'boolean', 'user', 'taxonomyRef'];
  (view.facets ?? []).forEach((c, i) => {
    const k = byKey.get(c)?.kind;
    if (k && !FACETABLE.includes(k)) {
      errors.push(`view.facets[${i}] must name a low-cardinality column, got ${k}`);
    }
  });

  if (view.style === 'blog' && !view.bodyColumn) {
    errors.push("view.style 'blog' requires bodyColumn — the long-form cell is the whole point of the style");
  }
  if (view.style === 'chat' && (!view.askColumn || !view.bodyColumn)) {
    errors.push(
      "view.style 'chat' requires askColumn and bodyColumn — an exchange with only one half is a grid row",
    );
  }
  if (view.style === 'timeline' && !view.dateColumn) {
    errors.push("view.style 'timeline' requires dateColumn — without it the order is arbitrary");
  }
  if (view.dateColumn) {
    const k = byKey.get(view.dateColumn)?.kind;
    if (k && k !== 'date' && k !== 'number' && k !== 'text') {
      errors.push(`view.dateColumn must be a date/number/text column, got ${k}`);
    }
  }
  return errors;
}

export const createTableRequestSchema = z
  .object({
    id: z.string().uuid().optional(),
    title: z.string().min(1).max(160),
    description: z.string().max(2000).optional(),
    driver: tableDriverSchema.default('libsql'),
    schema: tableSchemaSchema,
    /** taxonomy anchors — where the table's card hangs in the universe */
    anchors: z.array(z.string()).max(8).default([]),
    visibility: tableVisibilitySchema.default('private'),
    /** explicit ACL beside the tier grade (dtt-share-model; §14.3 code-
     *  declared access compiles down to this) */
    sharedWith: sharedWithSchema.default([]),
    /** graph-render metadata (S2⁶) — absent = card-only, byte-identical */
    graph: graphMetaSchema.optional(),
    /** render metadata (face surfaces) — absent = the grid, byte-identical */
    view: viewMetaSchema.optional(),
  })
  .superRefine((val, ctx) => {
    if (val.view) {
      for (const message of validateViewMeta(val.view, val.schema.columns)) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, message, path: ['view'] });
      }
    }
    const g = val.graph;
    if (!g) return;
    const byKey = new Map(val.schema.columns.map((c) => [c.key, c]));
    const requireColumn = (col: string | undefined, path: (string | number)[]) => {
      if (col === undefined) return;
      if (!byKey.has(col)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `graph references unknown column: ${col}`,
          path,
        });
      }
    };

    // mode:'rows' ⇒ node present, node.labelColumn names a real column.
    if (g.mode === 'rows' && !g.node) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "graph.mode 'rows' requires graph.node",
        path: ['graph', 'node'],
      });
    }

    // Node column refs must name real columns.
    if (g.node) {
      requireColumn(g.node.labelColumn, ['graph', 'node', 'labelColumn']);
      requireColumn(g.node.idColumn, ['graph', 'node', 'idColumn']);
      if (g.node.anchorColumn !== undefined) {
        requireColumn(g.node.anchorColumn, ['graph', 'node', 'anchorColumn']);
        const col = byKey.get(g.node.anchorColumn);
        if (col && col.kind !== 'taxonomyRef') {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: `graph.node.anchorColumn must be a taxonomyRef column, got ${col.kind}`,
            path: ['graph', 'node', 'anchorColumn'],
          });
        }
      }
    }

    // Edge column refs must name real columns, kind-compatible with toKind.
    g.edges.forEach((e, i) => {
      requireColumn(e.column, ['graph', 'edges', i, 'column']);
      const col = byKey.get(e.column);
      if (!col) return;
      const wantKind =
        e.toKind === 'object' ? 'objectRef' : e.toKind === 'row' ? 'rowRef' : 'taxonomyRef';
      if (col.kind !== wantKind) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `graph.edges[${i}].column kind ${col.kind} is not compatible with toKind '${e.toKind}' (needs ${wantKind}; a user→node mapping does not exist in Stage 1)`,
          path: ['graph', 'edges', i, 'column'],
        });
      }
    });
  });
export type CreateTableRequest = z.infer<typeof createTableRequestSchema>;

/**
 * PATCH /api/tables/:id with a `schema` — reconcile the column schema of a
 * table that already exists. Both fields optional and independent, so the
 * endpoint stays the single "change this table's declaration" surface rather
 * than growing a second one; a body with neither is rejected at the route.
 */
export const updateTableSchemaSchema = z.object({
  visibility: tableVisibilitySchema.optional(),
  /** Replace the table's explicit ACL — owner/admin only (a write GRANTEE
   *  edits rows, never the shares). */
  sharedWith: sharedWithSchema.optional(),
  schema: tableSchemaSchema.optional(),
  /** Change how the table renders without touching its columns. Validated
   *  against the LIVE schema at the route, since the columns may not be in
   *  this request at all. */
  view: viewMetaSchema.optional(),
});
export type UpdateTableSchema = z.infer<typeof updateTableSchemaSchema>;

export interface TableInfo {
  id: string;
  title: string;
  description?: string;
  driver: TableDriver;
  schema: TableSchema;
  capabilities: TableCapabilities;
  ownerId: string;
  visibility: string;
  /** Explicit ACL beside the tier grade (dtt-share-model). */
  sharedWith: ShareEntry[];
  rowCount: number;
  createdAt: number;
  updatedAt: number;
}

export interface TableRow {
  id: string;
  values: Record<string, unknown>;
  createdAt: number;
  updatedAt: number;
  updatedBy: string;
  /** Row-level sharing triple; absent = governed entirely by the table. */
  sharing?: RowSharing;
}
