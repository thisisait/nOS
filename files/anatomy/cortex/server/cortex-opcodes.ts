/**
 * cortex-opcodes — the code-owned opcode registry and the namespace policy
 * tables for `POST /agent/v1/validate` (docs/specs/cortex-validate.md, D2/D3/D1).
 *
 * Decision D2: this registry is a frozen `as const` literal compiled into the
 * build. It is NOT a table, NOT a migration, NOT a seed and above all NOT
 * `relation_types` — anything in SQLite is writable by some path (any RW bearer
 * can plant a `status='proposed'` row), and a capability set reachable from the
 * pipeline that consumes it is not a capability set. Adding an opcode is a
 * reviewable diff with a release, which is the correct ceremony for "the system
 * can now do a new thing".
 *
 * Decision D3: the contract with Wing is one-directional. Wing is the source of
 * truth for *handler existence*; this table is authoritative for *validation*.
 * Ordering rule for adding a capability: Wing ships the handler FIRST, KEAP
 * enables the opcode SECOND (fail closed).
 *
 * What this module must never acquire: a list of databases, services or
 * documents. Knowing the seven namespace *tokens* is grammar (plan §3); knowing
 * which `db:` resources exist is the coupling the two-authority split removed.
 *
 * Pure: no DB, no express, no I/O. `node:crypto` is used for the registry
 * fingerprint, which is a pure function of this file.
 */
import { createHash } from 'node:crypto';

/** Cortex contract version. Published at `GET /agent/v1/health` as
 *  `contracts.cortex`. Increments on any incompatible change to this registry,
 *  the AST schema or the error codes. `contracts.selfmodel` is never bumped. */
export const CORTEX_CONTRACT_VERSION = 1;

// ---------------------------------------------------------------------------
// Namespaces (grammar §3: a closed seven-symbol enum)
// ---------------------------------------------------------------------------

export const CORTEX_NAMESPACES = ['tax', 'ent', 'kg', 'rel', 'db', 'svc', 'doc'] as const;
export type CortexNamespace = (typeof CORTEX_NAMESPACES)[number];

const NAMESPACE_SET: ReadonlySet<string> = new Set<string>(CORTEX_NAMESPACES);

export function isCortexNamespace(value: string): value is CortexNamespace {
  return NAMESPACE_SET.has(value);
}

/**
 * D1 — the namespace policy, the whole identity model as data.
 *
 * - `resolved`   — KEAP resolves it at system scope. Legal only for layers that
 *                  are ownerless, visibility-free and already enumerable
 *                  wholesale by the same bearer (`tax:`, `rel:`).
 * - `unresolved` — KEAP refuses at namespace granularity with a constant,
 *                  operand-independent `namespace_not_resolvable`. NO DB call is
 *                  issued: issuing one and discarding the result would keep the
 *                  timing oracle.
 * - `deferred`   — Wing's phase 2. KEAP checks shape only and never learns what
 *                  resources exist.
 */
export type CortexNamespacePolicy = 'resolved' | 'unresolved' | 'deferred';

export const NAMESPACE_POLICY: Readonly<Record<CortexNamespace, CortexNamespacePolicy>> = {
  tax: 'resolved',
  rel: 'resolved',
  kg: 'unresolved',
  ent: 'unresolved',
  db: 'deferred',
  svc: 'deferred',
  doc: 'deferred',
};

/** The machine-readable scope declaration returned as `data.scope` (§3.2).
 *  `authorizes` is a literal `false`: a `valid: true` AST is a statement about
 *  meaning, never about permission. Derived from NAMESPACE_POLICY; the unit
 *  suite asserts the two cannot drift. */
export const CORTEX_SCOPE = {
  model: 'system-ontology',
  authorizes: false,
  resolved: ['tax', 'rel'],
  unresolved: ['kg', 'ent'],
  deferred: ['db', 'svc', 'doc'],
} as const;

/**
 * D6 — reserved scope words. Legal ONLY in the `dotted_id` slot of a
 * bracket-carrying (late-binding) operand: `tax:node[…]`, `rel:verb[…]`,
 * `kg:object[…]`. `tax:node` without a bracket is `malformed_operand`, never a
 * lookup for a node whose id is literally "node".
 *
 * `ent:` has no reserved word — its scope hint is any entity type slug (and is
 * unresolvable in P1 either way).
 */
export const RESERVED_SCOPE_WORDS: Readonly<Partial<Record<CortexNamespace, string>>> = {
  tax: 'node',
  rel: 'verb',
  kg: 'object',
};

// ---------------------------------------------------------------------------
// Opcode specs
// ---------------------------------------------------------------------------

export type CortexParamType = 'bool' | 'int' | 'string' | 'id';

export interface CortexParamSpec {
  readonly type: CortexParamType;
  /** required = must be present, with or without the `?` default marker. */
  readonly required: boolean;
  /** Documentary only. NEVER injected into `params` (D8) — a computed default
   *  travels in the stage's separate `effective` block. */
  readonly default?: boolean | number | string;
}

export interface CortexOpcodeSpec {
  /** the surface token; matches /^[a-z][a-z0-9-]{0,31}$/ */
  readonly name: string;
  /** one line, published in the registry and in the P2 primer */
  readonly summary: string;
  /** arity is positional min/max over ENTITY args only — kv args are matched by
   *  name and do not count, which removes the "is dry_run=true an argument?"
   *  ambiguity entirely. `namespaces` is per-opcode, not per-slot (§2.2). */
  readonly operands: {
    readonly min: number;
    readonly max: number;
    readonly namespaces: readonly CortexNamespace[];
  };
  readonly params: Readonly<Record<string, CortexParamSpec>>;
  /** the handler can change durable state in any system. A property of the
   *  VERB, declared by KEAP, enforced by Wing. */
  readonly mutating: boolean;
  /** the cortex contract version that introduced this opcode */
  readonly since: number;
}

const MUTATION_PARAMS = {
  dry_run: { type: 'bool', required: false, default: true },
  commit: { type: 'bool', required: false, default: false },
  idempotency_key: { type: 'string', required: false },
} as const;

const GATE_PARAMS = {
  dry_run: { type: 'bool', required: false, default: true },
  commit: { type: 'bool', required: false, default: false },
} as const;

/**
 * The P1 opcode set (spec §2.3), derived from plan §3.
 *
 * `branch` is EXCLUDED: plan §10 keeps the IR flat through P3, and declaring an
 * opcode the grammar cannot express is how a deferred decision leaks into
 * training material.
 *
 * Two judgment calls, recorded so they are not silently reversed:
 * - `embed` is non-mutating. It is a projection stage producing a vector for the
 *   next stage. If a Wing handler ever *persists* embeddings, the handler is
 *   wrong, not this table.
 * - `link` is mutating. It writes a relation row, and it is the only mutating
 *   verb in the P1 set whose target namespace is ontology-backed.
 */
export const CORTEX_OPCODES = [
  {
    name: 'get',
    summary: 'fetch the operand’s record',
    operands: { min: 1, max: 1, namespaces: ['tax', 'kg', 'db', 'svc', 'doc'] },
    params: {
      limit: { type: 'int', required: false },
      fields: { type: 'string', required: false },
    },
    mutating: false,
    since: 1,
  },
  {
    name: 'map',
    summary: 'project each item of the input through the operand',
    operands: { min: 1, max: 1, namespaces: ['tax', 'ent', 'kg'] },
    params: {},
    mutating: false,
    since: 1,
  },
  {
    name: 'filter',
    summary: 'keep the items of the input that match the operand',
    operands: { min: 0, max: 1, namespaces: ['tax', 'ent', 'kg'] },
    params: { where: { type: 'string', required: false } },
    mutating: false,
    since: 1,
  },
  {
    name: 'rank',
    summary: 'order the input by a signal',
    operands: { min: 0, max: 1, namespaces: ['tax', 'kg'] },
    params: {
      by: { type: 'string', required: false },
      limit: { type: 'int', required: false },
    },
    mutating: false,
    since: 1,
  },
  {
    name: 'classify',
    summary: 'assign the input to an ontology node',
    operands: { min: 1, max: 1, namespaces: ['tax', 'kg'] },
    params: { threshold: { type: 'int', required: false } },
    mutating: false,
    since: 1,
  },
  {
    name: 'resolve',
    summary: 'resolve a surface term to a canonical operand',
    operands: { min: 1, max: 1, namespaces: ['tax', 'ent', 'kg', 'rel'] },
    params: {},
    mutating: false,
    since: 1,
  },
  {
    name: 'embed',
    summary: 'project the input into vector space',
    operands: { min: 0, max: 1, namespaces: ['tax', 'kg', 'doc'] },
    params: { model: { type: 'string', required: false } },
    mutating: false,
    since: 1,
  },
  {
    name: 'link',
    summary: 'assert a typed relation between operands',
    operands: { min: 1, max: 2, namespaces: ['rel', 'tax', 'kg'] },
    params: MUTATION_PARAMS,
    mutating: true,
    since: 1,
  },
  {
    name: 'insert',
    summary: 'create a record in the operand’s store',
    operands: { min: 1, max: 1, namespaces: ['db', 'svc'] },
    params: MUTATION_PARAMS,
    mutating: true,
    since: 1,
  },
  {
    name: 'update',
    summary: 'modify a record in the operand’s store',
    operands: { min: 1, max: 1, namespaces: ['db', 'svc'] },
    params: MUTATION_PARAMS,
    mutating: true,
    since: 1,
  },
  {
    name: 'delete',
    summary: 'remove a record from the operand’s store',
    operands: { min: 1, max: 1, namespaces: ['db', 'svc'] },
    params: MUTATION_PARAMS,
    mutating: true,
    since: 1,
  },
  {
    name: 'preserve',
    summary: 'capture the input into durable storage',
    operands: { min: 1, max: 1, namespaces: ['kg', 'doc', 'db'] },
    params: MUTATION_PARAMS,
    mutating: true,
    since: 1,
  },
  {
    name: 'route',
    summary: 'hand the input to a service or document sink',
    operands: { min: 1, max: 1, namespaces: ['svc', 'doc'] },
    params: GATE_PARAMS,
    mutating: true,
    since: 1,
  },
  {
    name: 'review',
    summary: 'queue the input for human moderation',
    operands: { min: 0, max: 1, namespaces: ['tax', 'kg', 'ent'] },
    params: GATE_PARAMS,
    mutating: true,
    since: 1,
  },
] as const satisfies readonly CortexOpcodeSpec[];

// Runtime immutability as well as compile-time: the registry is a capability
// set, and a capability set that a later import can push onto is not one.
for (const op of CORTEX_OPCODES) {
  Object.freeze(op.operands.namespaces);
  Object.freeze(op.operands);
  for (const param of Object.values(op.params as Record<string, CortexParamSpec>)) Object.freeze(param);
  Object.freeze(op.params);
  Object.freeze(op);
}
Object.freeze(CORTEX_OPCODES);

const OPCODE_INDEX: ReadonlyMap<string, CortexOpcodeSpec> = new Map(
  CORTEX_OPCODES.map((op) => [op.name, op] as [string, CortexOpcodeSpec]),
);

export function getOpcode(name: string): CortexOpcodeSpec | undefined {
  return OPCODE_INDEX.get(name);
}

export function opcodeNames(): readonly string[] {
  return CORTEX_OPCODES.map((op) => op.name);
}

export function listOpcodes(): readonly CortexOpcodeSpec[] {
  return CORTEX_OPCODES as readonly CortexOpcodeSpec[];
}

// ---------------------------------------------------------------------------
// `didYouMean` suggestions
// ---------------------------------------------------------------------------

function editDistance(a: string, b: string): number {
  const rows = a.length + 1;
  const cols = b.length + 1;
  let prev = new Array<number>(cols);
  let curr = new Array<number>(cols);
  for (let j = 0; j < cols; j += 1) prev[j] = j;
  for (let i = 1; i < rows; i += 1) {
    curr[0] = i;
    for (let j = 1; j < cols; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      curr[j] = Math.min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost);
    }
    const swap = prev;
    prev = curr;
    curr = swap;
  }
  return prev[cols - 1];
}

/** Suggestions for `unknown_opcode`. Safe to publish: the registry itself is
 *  published at `GET /agent/v1/validate/opcodes`, so a suggestion discloses
 *  nothing the caller cannot already enumerate. Case-insensitive so a
 *  `Classify` typo gets a remedy; distance ≤ 2, at most 3 entries. */
export function suggestOpcodes(name: string): string[] {
  const needle = name.toLowerCase();
  return CORTEX_OPCODES.filter((op) => op.name !== name)
    .map((op) => ({ name: op.name, d: editDistance(needle, op.name) }))
    .filter((c) => c.d <= 2)
    .sort((a, b) => a.d - b.d || a.name.localeCompare(b.name))
    .slice(0, 3)
    .map((c) => c.name);
}

// ---------------------------------------------------------------------------
// Registry fingerprint (§2.4)
// ---------------------------------------------------------------------------

/**
 * Canonical serialization of the registry — LF-joined, no trailing newline.
 * One line per opcode, sorted by name; params sorted by key.
 *
 *   o \t name \t since \t mutating(1|0) \t min \t max \t ns,ns,… \t key:type:r|o[:default] | …
 *
 * `summary` is deliberately EXCLUDED, on the same reasoning §3.4 excludes a
 * node's `description`: it is prose that churns editorially, and invalidating
 * every stored precedent on a wording fix costs more than it buys. Everything
 * that changes what a program MEANS is in the line.
 */
export function canonicalOpcodeRegistry(): string {
  return [...CORTEX_OPCODES]
    .map((op) => op as CortexOpcodeSpec)
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((op) => {
      const params = Object.keys(op.params)
        .sort()
        .map((key) => {
          const p = op.params[key];
          const req = p.required ? 'r' : 'o';
          const def = p.default === undefined ? '' : `:${String(p.default)}`;
          return `${key}:${p.type}:${req}${def}`;
        })
        .join('|');
      return [
        'o',
        op.name,
        String(op.since),
        op.mutating ? '1' : '0',
        String(op.operands.min),
        String(op.operands.max),
        [...op.operands.namespaces].join(','),
        params,
      ].join('\t');
    })
    .join('\n');
}

let registryHashCache: string | null = null;

/** `cx1:<first 16 hex of sha256(canonicalOpcodeRegistry())>`. Stamped into every
 *  AST as `binding.opcodeRegistryHash` and published as `registryHash` — it is
 *  the drift axis that catches a KEAP release changing arity between validate
 *  and dispatch. */
export function cortexRegistryHash(): string {
  if (registryHashCache === null) {
    const digest = createHash('sha256').update(canonicalOpcodeRegistry(), 'utf8').digest('hex');
    registryHashCache = `cx1:${digest.slice(0, 16)}`;
  }
  return registryHashCache;
}
