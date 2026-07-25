# cortex-validate — KEAP's half of nos-cortex-lang P1

> **Status:** design spec, frozen for implementation. Written against KEAP
> v1.26.0 on `feat/cortex-validate`.
> **Scope:** `POST /agent/v1/validate` — tokenize → parse → typecheck against the
> live ontology → **AST or typed errors**. Zero side effects, zero writes, no LLM
> in the container.
> **Authorities:** the nOS plan `docs/plans/nos-cortex-lang.md` (frozen P0) and
> this repo's `docs/specs/nos-cortex-lang-review-02.md` (which is the source of
> the plan's §4–§6). Where this spec departs from the plan it says so, in a box,
> with the reason.

This document decides everything an implementer would otherwise decide by
accident. It contains **no implementation code** — it contains the contract,
the decisions, and the test vectors that pin them.

---

## 0. Summary of decisions

| # | Question | Decision |
|---|---|---|
| 1 | Identity model | **Declared restricted scope, refused at namespace granularity.** `tax:`/`rel:` resolve at system scope (a strict subset of what the same token already reads); `kg:`/`ent:` are **not resolvable in P1** and return a constant, operand-independent error. §1 |
| 2 | Opcode registry | A frozen `as const` table in KEAP code (`server/cortex/opcodes.ts`), never in SQLite, never in `relation_types`. Published, hashed, and gated cross-repo against Wing's handler map. §2 |
| 3 | AST schema | §3. `ontology.version` is a **content hash of the live operand vocabulary** — a new, additive field, defined here because nothing equivalent exists. |
| 4 | Error taxonomy | 15 typed codes + 4 warning/info codes, severity-tagged, returned as **data inside a 200**. §4 |
| 5 | Deferred validation | `kind:"deferred"` operand nodes + a top-level `deferred[]` index. KEAP guarantees **structural well-formedness only**. §5 |
| 6 | `dry_run` on mutating verbs | **Report, never inject into `params`.** A separate, clearly-labelled `effective` block carries the computed default; `params` stays a verbatim record of what the model emitted. §6 |
| 7 | P1 non-goals | §7 |

---

## 1. The identity model

### 1.1 The situation, stated without euphemism

`/agent/v1/*` has **no authenticated caller identity**. `agentAuth`
(`server/agent.ts:59`) establishes exactly one bit — `'ro' | 'rw'` — from one of
two process-wide shared secrets (`server/tokens.ts:18`). `req.agentName` is the
raw `X-Keap-Agent` request header, truncated to 64 chars, unvalidated and
unbound to the token: **self-asserted**. `req.user` is not merely unset, it is
structurally unreachable — `registerAgentRoutes(app)` runs at
`server/index.ts:102`, `app.use(identityMiddleware)` at `server/index.ts:113`, so
no `/agent/v1` handler can ever see a user, and sending `X-Authentik-*` headers
directly would be forgery anyway.

The gates that would answer "may this caller read this?" are
`db.canReadObject(id, userId, seeAll, groups)` (`server/db.ts:1018`) and
`db.getVisibleObjects(...)` (`server/db.ts:1325`). Both require a `groups: string[]`,
deliberately with no default. **`groups: []` is not a neutral value** —
`tierRank([]) === 4 === guest` (`server/rbac.ts:40`), so an empty array silently
answers as a guest, which is *safe* but *wrong* for a manager and the caller
cannot tell.

So the plan's §5.1 requirement — "resolve operands against the calling identity"
— has, today, **no identity to resolve against**. Any implementation that claims
otherwise is lying about what it enforces.

### 1.2 The decision

> **Decision D1 — validate runs at a declared, restricted scope, and the
> restriction is applied per namespace, not per operand.**
>
> - `tax:` and `rel:` are **resolved** at system scope.
> - `kg:` and `ent:` are **not resolved at all** in P1. Every `kg:`/`ent:`
>   operand — existing or not, readable or not — returns the identical typed
>   error `namespace_not_resolvable`.
> - `db:`, `svc:`, `doc:` are **deferred** to Wing (§5).
> - The response **declares this scope machine-readably** (`data.scope`), so no
>   consumer has to infer it.

This is option (d) in the stage brief — "something better" — and it is better
than (a), (b) and (c) for a specific reason:

**A refusal that is constant per namespace leaks zero bits about any operand.**
The plan's uniform-`unknown operand` rule exists because *distinguishable errors
are the disclosure*. A namespace that is never resolved cannot produce
distinguishable errors, because the answer is a function of the namespace token
alone and not of the operand. It is therefore strictly safer than a uniform
`unknown operand`, and — unlike a uniform `unknown operand` for a namespace we
secretly could resolve — it is also **honest**: it does not tell the caller
"that does not exist" about something that does.

### 1.3 Why `tax:` and `rel:` resolving at system scope is not a disclosure

This is a strict-subset argument, not a hand-wave:

- **Taxonomy nodes have no owner and no visibility column.** `FlatNode`
  (`server/taxonomy.ts:23`) has no such field; `visibleTo` in
  `server/search.ts:56` returns `true` unconditionally for `kind === 'taxonomy'`.
  The same RO bearer already enumerates the whole tree wholesale via
  `GET /agent/v1/taxonomy/search` and `GET /agent/v1/graph`.
- **Relation types are a 16-row published vocabulary.** `GET /agent/v1/relations`
  hands the same token the entire list.

`validate` therefore answers, for these two namespaces, **questions the caller
can already answer with two existing GETs**. It adds no new capability and no new
disclosure. That is the whole justification, and it is why ambiguity candidates
over `tax:` are also safe (§4.4).

### 1.4 Why `kg:`/`ent:` are refused rather than resolved

- **`kg:`** is `knowledge_objects`, which *is* genuinely tier-scoped
  (`readableVisibilitiesFor`, `server/rbac.ts:81`) and *is* the enumeration-oracle
  surface. `db.getObject(id)` (`server/db.ts:1007`) is visibility-agnostic — a
  plain `SELECT * WHERE id = ?`. Resolving `kg:` with it would build, in a new
  endpoint, exactly the bug class v1.17 fixed in `GET /api/objects/:id`.
  Resolving it with `canReadObject` and `groups: []` would silently answer as a
  guest and return `unknown_operand` for most real cards — the same refusal, with
  more code and a false claim of authorization.
- **`ent:`** has **no backing at all**. `object_type_definitions`
  (`server/migrations.ts:60`) is created by migration 001 and touched by **zero
  lines of code** in the repo — no reader, no writer, no accessor. The review
  (`nos-cortex-lang-review-02.md:43`) named it as *"the plausible backing"*; that
  was a naming recommendation to the nOS side, not a statement that it has rows.
  The only live typing surface is `db.objectTypes()` (`server/db.ts:1076`) =
  `SELECT DISTINCT type FROM knowledge_objects`, which is an *observed* enum with
  no visibility filter — an instance-derived leak, not a registry.

  > **Departure from the plan.** Plan §4 and checklist item 1 say
  > "`ent:` → `object_type_definitions`". KEAP cannot implement that in P1,
  > because the table is empty dead schema. Validating against it would produce a
  > route that *appears* to typecheck `ent:` and in fact rejects everything.
  > This spec refuses `ent:` explicitly instead, and §7 names populating that
  > registry as the P3 prerequisite.

### 1.5 Options explicitly rejected

- **(b) A new capability-scoped token type carrying an identity binding** —
  correct, and it is the destination (plan §5.2), but it is **not a KEAP-only
  change**: nOS must mint, hold, rotate and audit per-identity tokens, and Wing
  must carry a subject. Building KEAP's half alone yields a token type with no
  issuer. Deferred to P3, with the migration path in §1.7. The only in-repo
  precedent, `extension_credentials` (`server/extension/store.ts:194`), maps a
  bearer to a real `KeapUser` — but hardcodes `groups: []` and `isAdmin: false`,
  parking every caller at guest rank. Copying it yields Option (a) with a
  migration.
- **(c) An explicit identity parameter (`X-Keap-On-Behalf-Of` or a body field)** —
  **rejected outright.** It is impersonation by assertion: the same trust level as
  `X-Keap-Agent`, so any RO-token holder resolves as any user, including an admin.
  It is strictly worse than refusing, because it *looks* like authz. It is only
  defensible once the bearer itself names a subject — i.e. it presupposes (b) and
  adds nothing on top of it. **It is written down here so it is rejected once
  rather than re-proposed.**

### 1.6 What this model does and does NOT protect against

**It protects against:**

- `validate` becoming a *new* oracle over the object corpus or entity registry.
  Neither is reachable through this endpoint at any input.
- Disclosure through the *shape* of an error: within `tax:`/`rel:` the answers
  `unknown_operand` (absent) and `unknown_operand` (registered-then-dropped ext
  orphan) are byte-identical; across `kg:`/`ent:` the answer is constant.

**It does NOT protect against, and must never be described as protecting against:**

1. **Taxonomy and verb enumeration by any RO-token holder.** That is already
   true of `/agent/v1/taxonomy/search` and `/agent/v1/relations`. `validate`
   inherits it and does not worsen it. If that enumeration is ever deemed
   unacceptable, the fix is at the surface level for all three routes, not here.
2. **Anything about authorization.** A `valid: true` AST is a statement about
   *meaning*, not *permission*. Wing must authorize independently at dispatch,
   per plan §5.2. `data.scope.authorizes: false` is in the response to make this
   un-missable.
3. **Spoofed attribution.** `X-Keap-Agent` remains self-asserted. **`validate`
   MUST NOT read it for any decision** — not for scope, not for rate limits, not
   for candidate filtering. It may be logged; it may not be believed.
4. **Existence disclosure through timing or size.** Not addressed. A caller who
   can measure response latency across many probes may distinguish an FTS hit
   from a miss within `tax:`. Accepted, because the tree is already public to
   this token.
5. **Denial of service.** No rate limiting exists on `/agent/v1/*` and this spec
   does not add any. Bounded by input caps (§3.6) only. Named as a real gap.

### 1.7 The forward path (so P3 does not re-litigate this)

When per-identity capability tokens exist (plan §5.2), the change is
**additive and local**:

1. The token resolves to a `{ userId, groups, isAdmin }` subject.
2. `kg:` moves from `unresolved` to `resolved` in the namespace policy table.
3. `kg:` resolution goes through `db.canReadObject(id, userId, isAdmin, groups)`
   — **never** `db.getObject`. Not-found and not-readable both produce the
   identical `unknown_operand`, per `server/routes.ts:416-427`.
4. **Ambiguity candidates for `kg:` must be filtered by the same gate before the
   list is built** — a candidate list assembled unfiltered re-opens exactly the
   disclosure the uniform error closes. Same for any count, score, or
   "did you mean" field.
5. `data.scope` changes value; no consumer changes shape.
6. Captures are **owner-only** (`db.canReadCapture`, `server/db.ts:666`) and do
   **not** go through the tier ladder. If capture operands are ever added, they
   need their own gate — the two are not interchangeable.

Until then, §1.2 stands.

---

## 2. The opcode registry

### 2.1 Where KEAP's copy lives

> **Decision D2 — the opcode registry is a frozen `as const` object literal in
> `server/cortex/opcodes.ts`, compiled into the build. It is not a table, not a
> migration, not a seed, and above all not `relation_types`.**

Rationale, beyond the plan's §2 argument (an LLM typing-run must never be able to
propose a new *system capability*):

- **Anything in SQLite is writable by some path.** `relation_types` grows under
  moderation and any RW bearer can plant a `status='proposed'` row by POSTing an
  unknown type to `/agent/v1/relations` (`server/db.ts:2644`). A capability set
  reachable from that pipeline is a capability set the pipeline can extend.
- **A `const` changes only by a release.** Adding an opcode becomes a reviewable
  diff with a version bump, which is the correct ceremony for "the system can now
  do a new thing".
- **It survives the esbuild bundle.** e2e runs against `dist-server/index.js`; a
  data file read at runtime would be a second failure mode (see the trap noted at
  `e2e/selfmodel.spec.ts:22`).

### 2.2 What each opcode declares

```
OpcodeSpec {
  name        : string          // the surface token; matches /^[a-z][a-z0-9-]{0,31}$/
  summary     : string          // one line, published in the registry
  operands    : { min: int, max: int, namespaces: Ns[] }
  params      : Record<key, ParamSpec>
  mutating    : boolean
  since       : int             // cortex contract version that introduced it
}

ParamSpec {
  type     : 'bool' | 'int' | 'string' | 'id'
  required : boolean            // required = must be present, with or without '?'
  default? : bool|int|string    // documentary; NEVER injected into params (§6)
}

Ns = 'tax' | 'ent' | 'kg' | 'rel' | 'db' | 'svc' | 'doc'
```

- **Arity is positional min/max over *entity* args.** `kv` args (`key=value`,
  `?key=value`) are matched by name against `params` and do not count toward
  arity. This removes the "is `dry_run=true` an argument?" ambiguity entirely.
- **`namespaces` is per-opcode, not per-slot.** Per-slot typing was considered and
  rejected: every opcode in the P1 set is either uniform in its operand kinds or
  takes exactly one operand, so per-slot typing would be unused machinery that
  the local model (P4/P5) must nonetheless learn. Revisit only when a real opcode
  needs it.
- **`mutating` means: the handler can change durable state in any system.** It is
  a property of the *verb*, declared by KEAP, enforced by Wing (§6).

### 2.3 The P1 opcode set

Derived from plan §3's list. `branch` is **excluded** — plan §10 keeps the IR flat
through P3, and declaring an opcode the grammar cannot express is how a deferred
decision leaks into training material.

| opcode | operands (min–max) | namespaces | mutating | params (key: type) |
|---|---|---|---|---|
| `get` | 1–1 | tax, kg, db, svc, doc | no | `limit:int`, `fields:string` |
| `map` | 1–1 | tax, ent, kg | no | — |
| `filter` | 0–1 | tax, ent, kg | no | `where:string` |
| `rank` | 0–1 | tax, kg | no | `by:string`, `limit:int` |
| `classify` | 1–1 | tax, kg | no | `threshold:int` |
| `resolve` | 1–1 | tax, ent, kg, rel | no | — |
| `embed` | 0–1 | tax, kg, doc | no | `model:string` |
| `link` | 1–2 | rel, tax, kg | **yes** | `dry_run:bool`, `commit:bool`, `idempotency_key:string` |
| `insert` | 1–1 | db, svc | **yes** | `dry_run:bool`, `commit:bool`, `idempotency_key:string` |
| `update` | 1–1 | db, svc | **yes** | `dry_run:bool`, `commit:bool`, `idempotency_key:string` |
| `delete` | 1–1 | db, svc | **yes** | `dry_run:bool`, `commit:bool`, `idempotency_key:string` |
| `preserve` | 1–1 | kg, doc, db | **yes** | `dry_run:bool`, `commit:bool`, `idempotency_key:string` |
| `route` | 1–1 | svc, doc | **yes** | `dry_run:bool`, `commit:bool` |
| `review` | 0–1 | tax, kg, ent | **yes** | `dry_run:bool`, `commit:bool` |

Two judgment calls, recorded so they are not silently reversed:

- **`embed` is non-mutating.** In Cortex it is a projection stage that produces a
  vector for the next stage. If a Wing handler ever *persists* embeddings, the
  handler is wrong, not this table.
- **`link` is mutating.** It writes a relation row. It is the only mutating verb
  in the P1 set whose target namespace is ontology-backed, so it is the one place
  where a `dry_run` warning and a resolved `tax:`/`rel:` operand co-occur.

### 2.4 Keeping in sync with Wing without learning about resources

The coupling §4 forbids is KEAP knowing **which databases exist**. Knowing that
the *token* `db:` exists is not that coupling — it is one symbol in a seven-symbol
closed enum written in the grammar (plan §3), and it must be in KEAP or KEAP
cannot even tell `db:products` from a syntax error.

> **Decision D3 — the registry is a one-directional, name-and-shape contract.
> Wing is the source of truth for *handler existence*; KEAP's table is
> authoritative for *validation*. Drift is a gate failure, never a silent
> divergence.**

Mechanism, all three parts required:

1. **KEAP publishes the registry.** `GET /agent/v1/validate/opcodes`
   (`agentAuth('ro')`) returns `{ contract: <int>, registryHash: <sha256-16>,
   opcodes: OpcodeSpec[] }`. `registryHash` is a hash of the canonical
   serialization of the table (§3.4 defines "canonical serialization" the same
   way for both hashes). It is the same array that would appear in a primer.
2. **KEAP declares the contract version.** `GET /agent/v1/health` gains
   `contracts: { selfmodel: 1, cortex: 1 }`. **Adding a key, never bumping
   `selfmodel`** — that field is asserted `toBe(1)` at `e2e/selfmodel.spec.ts:35`
   and compared by the nOS cross-repo wet gate. `cortex` increments on any
   incompatible change to the registry, the AST schema, or the error codes.
3. **Wing asserts at boot and in CI.** Wing fetches the published registry and
   compares it to its handler-map keys. `handlers ⊉ opcodes` → Wing refuses to
   start (it would accept ASTs it cannot dispatch). `handlers ⊃ opcodes` → a
   logged warning only; those handlers are unreachable, which is harmless.

**Ordering rule for adding a capability:** Wing ships the handler **first**, KEAP
enables the opcode **second**. The failure mode of the wrong order is a
`valid: true` AST that dies at dispatch — an error surfaced far from its cause,
after the model has already been taught that the opcode works. The failure mode
of the right order is an unreachable handler.

**What KEAP must never acquire:** a list of databases, services, documents,
connection strings, or anything that would let `validate` answer *"does
`db:products` exist?"*. The correct P1 answer to that question is, and remains,
"ask Wing" (§5).

---

## 3. The AST schema

### 3.1 Transport

- **Route:** `POST /agent/v1/validate`, registered inside `registerAgentRoutes`
  (`server/agent.ts:120`), guarded by **`agentAuth('ro')`**.
  RO, not RW: the endpoint has zero side effects, and requiring a write token to
  typecheck would force the executor to hold write credentials for a read
  operation — exactly backwards. (Auth ladder is unchanged: 503 no token
  configured / 401 missing / 401 invalid.)
- **Envelope:** the local `ok`/`fail` from `server/agent.ts:41`. **Do not import
  the lookalike from `server/extension/routes.ts:29`** — that one takes a status
  parameter and would silently change the contract.
- **A validation report is data, not a transport error.** Follows the precedent
  of `POST /agent/v1/taxonomy/describe` (`server/agent.ts:908`): the report is
  returned as `200 {success:true, data:{...}}` **whether or not the program is
  valid**. `fail(res, 400, …)` is reserved for a malformed *request envelope*
  (missing `source`, wrong type, oversize).
- **Request body:**
  ```json
  { "source": "<string>", "ttlSeconds": 900 }
  ```
  `ttlSeconds` optional, clamped to `[60, 3600]`, default `900`. Validated with a
  zod schema in `shared/contracts/cortex.ts` using the `parse<T>` idiom at
  `server/extension/routes.ts:46`. **zod is already a production dependency**
  (`package.json:110`, used at `server/agent.ts:633`) — this adds nothing to
  `package-lock.json`. The *tokenizer* is hand-written; only the envelope is zod.
- **No `{ ast }` input in P1.** Revalidation at dispatch (§3.5) re-POSTs
  `ast.source`, which the AST carries verbatim. An AST-input path is P2 work and
  would need its own trust model.

### 3.2 Response shape

```json
{
  "success": true,
  "data": {
    "valid": true,
    "phase": 1,
    "complete": false,
    "scope": {
      "model": "system-ontology",
      "authorizes": false,
      "resolved":   ["tax", "rel"],
      "unresolved": ["kg", "ent"],
      "deferred":   ["db", "svc", "doc"]
    },
    "ast": { /* §3.3, null when valid === false */ },
    "errors":   [ /* §4 */ ],
    "warnings": [ /* §4, severity warning|info */ ]
  }
}
```

- `valid` — no `severity:"error"` entries. `warnings` may be non-empty.
- `phase: 1` — this is KEAP's half only.
- `complete` — `true` iff `valid && ast.deferred.length === 0`. A consumer that
  wants "can I dispatch this without Wing's phase 2?" reads exactly this field.
- `scope.authorizes: false` — a literal constant. It exists so that no downstream
  reader can mistake `valid: true` for permission (§1.6.2).
- `ast` is `null` whenever `valid === false`. A partial AST is a repair-loop
  temptation and a training-data hazard; there is no half-valid program.

### 3.3 The AST

```json
{
  "astVersion": 1,
  "source": "@input | classify(tax:node[Kinematics]) | insert(db:products, ?hidden=true, dry_run=true)",
  "pipeline": {
    "source": "@input",
    "stages": [
      {
        "index": 0,
        "opcode": "classify",
        "mutating": false,
        "operands": [
          {
            "ns": "tax",
            "kind": "resolved",
            "binding": "late",
            "scopeHint": "node",
            "surface": "Kinematics",
            "id": "01.01.01.01",
            "resolvedName": "Kinematics",
            "span": [22, 42]
          }
        ],
        "params": {},
        "effective": {}
      },
      {
        "index": 1,
        "opcode": "insert",
        "mutating": true,
        "operands": [
          {
            "ns": "db",
            "kind": "deferred",
            "binding": "exact",
            "scopeHint": null,
            "surface": "products",
            "id": null,
            "resolvedName": null,
            "span": [53, 64]
          }
        ],
        "params": {
          "hidden":  { "value": true, "defaulted": true,  "span": [66, 79] },
          "dry_run": { "value": true, "defaulted": false, "span": [81, 94] }
        },
        "effective": { "dry_run": true }
      }
    ]
  },
  "deferred": [ { "stage": 1, "operand": 0, "ns": "db" } ],
  "binding": {
    "ontologyVersion": "onto1:9f2a4c1b7d3e5a60",
    "databaseId": "b1f0…-uuid",
    "opcodeRegistryHash": "cx1:41c8b2ee9a730d55",
    "validatedAt": "2026-07-24T10:15:00.000Z",
    "expiresAt":   "2026-07-24T10:30:00.000Z",
    "ttlSeconds": 900
  }
}
```

**Operand node fields, and why each exists:**

| field | meaning | required by |
|---|---|---|
| `ns` | one of the seven namespace tokens | grammar |
| `kind` | `resolved` \| `deferred` \| `literal` | §5 |
| `binding` | `exact` (dotted id written directly) \| `late` (bracket term) | §6.1 audit |
| `scopeHint` | the `dotted_id` slot when `binding === "late"` (§3.7); else `null` | §3.7 |
| `surface` | **the text the model actually wrote** — the id for `exact`, the bracket term for `late` | plan §3: "the AST carries **both** the surface term and the resolved id" |
| `id` | the canonical resolved id; `null` unless `kind === "resolved"` | plan §3 |
| `resolvedName` | **the name that id had at resolution time** | plan §6.3 — drift invalidation, the `priorNames` check |
| `span` | `[startOffset, endOffset)` into `source`, character offsets | repair loop, error anchoring |

**Param nodes:** `params` is a **verbatim** record of what the model emitted.
`defaulted: true` encodes the `?key=value` form (plan §3: "`?key=value` = default
when absent"), which is semantically distinct from `key=value` and must not be
flattened. `effective` is a **separate, computed** block (§6).

### 3.4 `ontologyVersion` — defined here, because nothing equivalent exists

Audited: `GET /agent/v1/health` publishes `ontology: { verbs, toeRelations,
curatedRelations, byStatus }` (`server/db.ts:463`) — **four counts, no version**.
`knowledge/ontology/manifest.json` has `"version": 1`, but that is the *file
format* version (`knowledge/_schema/ontology-format.md`) and is not read by the
server at runtime. There is no ontology version in this codebase.

> **Decision D4 — `ontology.version` is a content hash of the live operand
> vocabulary, published additively at `GET /agent/v1/health` as
> `ontology.version`, and stamped into every AST.**

Canonical serialization (LF-joined, no trailing newline), then `sha256`, then
the first 16 hex chars, prefixed `onto1:`:

```
t\t<node.id>\t<node.parentId | "-">\t<node.name>      for every node in allNodes(), sorted by id ASC
r\t<type>\t<status>                                    for every relation_types row with
                                                       status IN ('seed','confirmed'), sorted by type ASC
```

**Why this composition, field by field:**

- **`allNodes()` (`server/taxonomy.ts:151`), not the `taxonomy_nodes_ext` table.**
  `registerExtNodes` deliberately *drops* rows whose parent never resolves or
  whose root id is not a bare slug (`server/taxonomy.ts:266`). The in-memory tree
  is exactly the set `getNode` will resolve, so the fingerprint describes the
  vocabulary validate actually used — not a superset on disk.
- **`id`** — the operand itself.
- **`name`** — a rename must invalidate a precedent (plan §6.3: store "the name
  it had at capture", compare on retrieval). Without `name` in the hash, a rename
  is invisible at the version level.
- **`parentId`** — a re-parent changes `node.path`, which `rebuildTaxonomyFts`
  indexes (`server/db.ts:1389`), which changes late-binding results. It is
  resolution-affecting and must be in the hash.
- **`description` is deliberately EXCLUDED.** K1 curated description overrides
  (`applyDescriptionOverride`, `server/taxonomy.ts:289`) change constantly and do
  not change which id a term resolves to *identically enough* to justify
  invalidating every stored precedent on every editorial fix. Accepted, named
  cost: a description edit can shift an FTS ranking without moving the version.
  This is the one place the fingerprint is deliberately coarse.
- **Relation types filtered to `status IN ('seed','confirmed')`** — the live
  vocabulary filter already used twice in the codebase (`server/agent.ts:432`,
  `server/agent.ts:562`). `'proposed'` rows are agent-grown and unmoderated;
  including them would let the same LLM pipeline that consumes the vocabulary
  move the version.

**Properties this buys:**

- No new table, no migration, no bump discipline, and it **cannot go stale** —
  it is derived, not declared.
- Stable across restarts when the content is stable; changes exactly when the
  operand vocabulary changes.
- **Boot-scoped, correctly.** The in-memory tree is built once at boot
  (`server/index.ts:45-56`); `knowledge/ingest.mjs` writes `taxonomy_nodes_ext`
  rows straight to the DB file and relies on a restart. Between ingest and
  restart, `getNode` answers "unknown" for ids that exist on disk. The
  fingerprint describes the tree the validator used, which is the correct
  semantics: the AST records what it was checked against, not what a different
  process believes.

**Implementation notes (not code):** compute lazily, memoize in a module-level
cache, and invalidate the cache from `registerExtNode` / `registerExtNodes`
(`server/taxonomy.ts:208, 250`), `insertProposedRelationType`, `setRelationTypeStatus`,
and `seedRelationTypes`. ~1840 lines + one sha256 is sub-millisecond; correctness
of invalidation matters more than the cost.

### 3.5 TTL, and why the fingerprint makes it an optimization

Plan §6.3 offers a choice: "either the AST carries a short **TTL**, or the
executor **revalidates at dispatch**."

> **Decision D5 — both, with different jobs. The TTL is a cheap-path hint; the
> `(ontologyVersion, databaseId, opcodeRegistryHash)` triple is the correctness
> mechanism.**

Wing's rule at dispatch, in order:

1. If `now > expiresAt` → **revalidate** (re-POST `ast.source`).
2. Else if live `health.ontology.version` ≠ `binding.ontologyVersion` →
   **revalidate**.
3. Else if live `health.database.id` ≠ `binding.databaseId` → **reject**, do not
   revalidate. A different database is a different language (plan §6.3); silently
   re-resolving against it is the identity-drift failure, one layer up.
4. Else dispatch.

A TTL alone is wrong because a converge can land one second after validation.
A version check alone is wrong because it requires a live health fetch on every
dispatch. `ttlSeconds` default **900** (15 min): long enough that a burst of
stages from one LLM turn reuses one validation, short enough that a stale AST
never survives an operator's coffee break. Clamped `[60, 3600]`.

`opcodeRegistryHash` catches the third drift axis: a KEAP release that changed
opcode arity between validate and dispatch.

### 3.6 Input bounds

Hard caps, each producing `program_too_large` with the limit and the observed
value. Rationale: `express.json({ limit: '2mb' })` (`server/index.ts:82`) is a
transport ceiling, not a semantic one, and late binding runs one FTS query per
late-bound operand.

| bound | limit |
|---|---|
| `source` length | 4096 characters |
| stages per pipeline | 16 |
| args per stage (operands + kv combined) | 16 |
| late-bound operands per program | 8 |
| bracket term length | 128 characters |
| dotted id length | 256 characters, ≤ 16 segments |
| errors returned | 20 (then truncated, with `truncated: true` on the report) |

### 3.7 Late binding: what the `dotted_id` slot means when a bracket is present

The grammar is `entity ::= ns ":" dotted_id ("[" term "]")?` — the dotted id is
**mandatory**, the bracket optional. Plan §3 describes the late-binding form as
`ns:type[human term]`, so when the bracket is present the `dotted_id` slot is a
**type or scope hint**, not an id. That is under-specified and would otherwise be
decided by accident. Decided here:

> **Decision D6 — when a bracket term is present, `dotted_id` is a scope hint,
> resolved per namespace:**
>
> | ns | legal scope hint | meaning |
> |---|---|---|
> | `tax` | the reserved word `node`, **or** an existing taxonomy id | search the whole tree, or only that node's subtree |
> | `rel` | the reserved word `verb` | search the 16 predicates by type and label |
> | `ent` | any entity type slug | not resolvable in P1 (§1.4) |
> | `kg` | the reserved word `object` | not resolvable in P1 (§1.4) |
> | `db`/`svc`/`doc` | anything grammar-legal | deferred; KEAP checks shape only (§5) |
>
> The reserved words `node`, `verb`, `object` are **only** legal in the scope-hint
> position. `tax:node` **without** a bracket is `malformed_operand`, not a lookup
> for a node whose id is "node".

Why a scope hint rather than ignoring the slot: it gives the repair loop a
**remedy**. On `ambiguous_operand`, the model re-emits with a narrower hint —
`tax:01.01[motion]` instead of `tax:node[motion]` — which is a single-token
correction against a candidate list the error already supplied. Without it, the
only remedy for ambiguity is "guess an id", which is precisely what late binding
exists to avoid.

### 3.8 Resolution algorithm (behaviour, not code)

**`tax:` exact** (`binding: "exact"`, no bracket):
1. Shape check against the canonical id regex (`server/objects.ts:27`) —
   `/^(?:\d{2}(?:\.\d{2})*|[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)*)$/`. The seed
   (dotted 2-digit) and grown (dotted lowercase slug) forms are structurally
   disjoint, so this prefilter is cheap and safe. Fail → `malformed_operand`.
2. `getNode(id)` (`server/taxonomy.ts:155`). **This is the only oracle** — never
   query `taxonomy_nodes_ext` directly, or dropped orphans become resolvable and
   the silent-orphan class the fixpoint exists to prevent comes back.
3. Miss → `unknown_operand`.

**`tax:` late** (bracket present):
1. If the scope hint is a taxonomy id, `getNode(hint)` must succeed; else
   `unknown_operand` on the **hint** (the hint is itself a `tax:` operand, and
   the tree is public to this token, so this is consistent with §1.3).
2. **Health check before the search:** if `db.countRows('taxonomy_fts') <= 0`,
   return `late_binding_unavailable` — *never* `unknown_operand`.
   `searchTaxonomyFts` swallows every error to `[]` (`server/db.ts:1404`) and
   `ftsQuery` returns `''` (→ `[]`) for whitespace-only input, so "index missing",
   "query malformed" and "genuinely no match" are otherwise the same empty array.
   Reporting a broken index as "unknown operand" teaches the model to rewrite a
   correct term.
3. `db.searchTaxonomyFts(term, 32)` → `FtsHit { id, rank }`. **Call it directly.**
   The existing helper `searchNodes` (`server/agent.ts:108`) discards `rank`,
   which is the only signal an ambiguity check has.
4. Filter to the subtree if a hint id was given (ancestor walk via
   `getAncestors`, `server/taxonomy.ts:159`).

   > **ERRATUM (implemented as corrected).** Steps 3–4 as written contradict
   > §3.7/D6 and §8 vector 3, which both promise the scope hint *narrows* rather
   > than filtering after the fact. `searchTaxonomyFts` applies `ORDER BY rank
   > LIMIT ?` in SQL, before the scope is known, so filtering a fixed 32-row page
   > answers "the best 32 in the **tree**" when the question was "the best 32 in
   > **this subtree**". Measured on the seed spine: all 32 global hits for
   > "engineering" live under `03.01`, so `tax:02.02[engineering]` — the subtree
   > named "Software Engineering" — filtered to zero and returned
   > `unknown_operand`, the exact mis-teaching step 2 exists to prevent, reached
   > through the remedy §3.7 hands back. Likewise `tax:06[technology]`, whose one
   > in-scope match ranks 171st of 212.
   >
   > 32 is therefore a **page size, not a horizon**: the implementation widens the
   > page (32 → 128 → 512 → 4096) until enough in-scope hits exist to rank, or the
   > index is exhausted, or the ceiling is reached. The whole-tree case never
   > escalates, so the common path still issues exactly one query.
   >
   > The same erratum applies to the exact-name refinement of step 5: node `02.01`
   > is named exactly "Mathematics" and ranks 32nd of 44, so a name-equality rule
   > answered from a ranking page could not fire for the very case it exists for,
   > and no hint could rescue it. Name equality is answered from the tree
   > (`allNodes()`, scoped by the same ancestor walk), not from an FTS page.
5. `rank` is fts5 bm25: **negative, more negative = better**. Sort ascending.
   Ambiguity rule: let `r0` be the best rank and `r1` the second. If
   `|r1 - r0| < 0.10 * |r0|` → **`ambiguous_operand`**, returning up to 5
   candidates. Otherwise take `r0`.
   > The 10 %-of-best-score margin is a **starting value, not a law.** It must be
   > pinned by the test vectors in §8 (rows 4 and 5 are the discrimination pair)
   > and re-tuned against them, on the model of `scripts/recall-gate.mjs` — a
   > threshold with no demonstrated discrimination is a number, not a guarantee.
6. Zero hits → `unknown_operand`.

**Never use `hybridSearch` for resolution.** Its `score` is Reciprocal Rank Fusion,
`1/(60 + rank + 1)` (`server/search.ts:25`): adjacent ranks differ by ~0.00026 and
the value is bounded to ~0.016 regardless of match quality. An ambiguity threshold
built on it fires on every query or on none.

**Vector search is a non-goal for P1 resolution.** It is unavailable in two
independent ways — the libSQL vector layer may not initialise
(`db.vectorSearchAvailable()`, `server/db.ts:493`) and free-text embedding needs
`KEAP_OLLAMA_URL`, unset by default (`embedText`, `server/embeddings.ts:122`).
FTS5 is the only path guaranteed to work in every deployment. **`validate` must
never return 503 for a missing vector layer** — nothing is wrong on that box.

**`rel:` exact:**
1. Shape check against `/^[a-z][a-z0-9-]{0,63}$/` (`server/agent.ts:338`). Fail →
   `malformed_operand`.
2. `db.getRelationType(type)` (`server/db.ts:2632`).
3. Valid **iff** the row exists **and** `status === 'seed' || status === 'confirmed'`.
   `'proposed'` → `unknown_operand`: those rows are plantable by any RW bearer
   POSTing an unknown type, and a vocabulary writable by the pipeline that
   consumes it is not a vocabulary.
   > **`rel:requires` IS valid.** `MECHANICAL_VERBS = new Set(['requires'])`
   > (`server/agent.ts:340`) is a **suggestion-time** filter for the classifier
   > only — the verb lists, renders and moderates everywhere else. Copying that
   > filter here would reject a legitimate seed-status predicate that the system
   > actively writes.
4. Do **not** validate against the `RelationStatus` union (`server/db.ts:2507`,
   `'proposed'|'confirmed'|'rejected'`) — that enum describes relation **rows**,
   not type rows, and `'seed'` is not a member of it. Using it rejects every
   seeded verb.

**`kg:` / `ent:` (exact or late):** `namespace_not_resolvable`, unconditionally,
before any lookup. **No database call is made.** This is not merely a policy
check — issuing the lookup and discarding the result would reintroduce the timing
oracle.

---

## 4. The error taxonomy

### 4.1 Entry shape

```json
{
  "code": "ambiguous_operand",
  "severity": "error",
  "message": "operand matches several nodes at comparable scores",
  "stage": 0,
  "offset": 22,
  "length": 20,
  "detail": { "ns": "tax", "surface": "motion", "candidates": [ … ] }
}
```

- `code` is **the contract**. `message` is prose for humans and repair prompts and
  is **not** stable across releases; no consumer may match on it.
- `offset`/`length` are character offsets into `source`, present whenever a span
  is known.
- `stage` is the 0-based stage index, `null` for program-level errors.
- `detail` is code-specific and **closed** — every field of it is listed below.
  Nothing is added ad hoc, because §1.6 depends on the error carrying no
  incidental information.

### 4.2 Codes

| code | severity | `detail` fields | when |
|---|---|---|---|
| `syntax_error` | error | `found`, `expected[]` | tokenize/parse failure. **Sole error returned** (§4.3) |
| `program_too_large` | error | `bound`, `limit`, `got` | any cap in §3.6 exceeded |
| `unknown_source` | error | `source`, `allowed[]` | not one of `@input @user @ctx @sel @prev` |
| `unknown_opcode` | error | `opcode`, `didYouMean[]` | not in the registry. Suggestions are safe: the registry is published (§2.4) |
| `arity_error` | error | `opcode`, `min`, `max`, `got` | wrong number of *entity* operands |
| `unknown_param` | error | `opcode`, `key`, `allowed[]` | `key` not in the opcode's `params` |
| `duplicate_param` | error | `key` | same key twice in one stage |
| `missing_required_param` | error | `opcode`, `key` | declared `required`, absent |
| `invalid_param_value` | error | `opcode`, `key`, `expectedType`, `got` | wrong literal type |
| `namespace_not_accepted` | error | `opcode`, `ns`, `allowed[]` | grammar-legal namespace, wrong verb |
| `malformed_operand` | error | `ns`, `surface`, `reason` | id fails the namespace's shape rule, or a reserved scope word used as an id (§3.7) |
| **`unknown_operand`** | error | `ns`, `surface` | **the uniform one.** Shape-legal, does not resolve. §4.3 |
| `ambiguous_operand` | error | `ns`, `surface`, `candidates[]` | comparable-score multimatch. §4.4 |
| `namespace_not_resolvable` | error | `ns`, `scope` | `kg:`/`ent:` under D1. **Constant per namespace** |
| `late_binding_unavailable` | error | `ns`, `reason` | the FTS index is absent or unbuilt (§3.8 step 2) |
| `deferred_namespace` | **info** | `ns` | `db:`/`svc:`/`doc:` operand. **Not an error** (§4.5) |
| `mutating_default_dry_run` | **warning** | `opcode` | mutating stage with no explicit `dry_run`/`commit` (§6) |
| `commit_requires_confirm_gate` | **warning** | `opcode` | explicit `commit=true` present (§6) |
| `deferred_program` | **info** | `count` | program-level: `deferred[]` is non-empty |

`valid === false` iff at least one entry has `severity: "error"`.

### 4.3 Uniformity, and error collection order

Phases run in this order; **a phase with errors does not run the next one**:

1. **Envelope** — zod. Failure → HTTP 400 `fail()`, not a report.
2. **Tokenize + parse.** On failure, return **exactly one** `syntax_error` at the
   first failure position and nothing else. Error recovery in a hand-written
   LL(1) parser is guessing; a resynchronized parse produces cascade errors that
   send the repair loop after phantoms. One accurate position beats five guesses.
3. **Structural** — opcode, arity, params, namespace acceptance. All errors
   collected.
4. **Resolution** — operands. All errors collected.

Phases 3 and 4 collect because the repair loop wants every fixable problem in one
round-trip; phase 2 does not, because it cannot do so honestly.

**The uniformity rule, stated as an invariant an implementer can test:** for any
two inputs that differ only in the *identity* of a shape-legal operand within one
namespace, the returned error entries must be byte-identical after substituting
`detail.surface`. Concretely:

- an absent `tax:` id and a `taxonomy_nodes_ext` row that was **dropped** at
  registration both yield `unknown_operand`;
- a `rel:` verb that never existed and one sitting at `status='proposed'` both
  yield `unknown_operand`;
- a `kg:` id that exists and one that does not both yield
  `namespace_not_resolvable`, with identical `detail`.

Test vectors 5/8/9/18 and the 6a/6b pair in §8 exist to pin exactly this.

### 4.4 Are ambiguity candidates a disclosure risk?

**Under D1: no — by construction.** Candidates can only ever come from `tax:` or
`rel:`, and:

- both layers are ownerless and visibility-free (§1.3);
- both are already enumerable wholesale by the same bearer via existing routes;
- `kg:`/`ent:` never reach the resolver, so no instance-level candidate list can
  be built even by mistake.

Candidate entry, closed shape — `{ id, name, path }`, capped at **5**:

```json
{ "id": "01.01.01.01.01", "name": "Motion equations",
  "path": "Natural Sciences > Physics > Classical Mechanics > Kinematics > Motion equations" }
```

`path` is included because it is the disambiguator a human or model actually uses;
it is already public in `/agent/v1/taxonomy/search`. **`rank`/`score` is
deliberately excluded** — it is an internal bm25 value with no cross-query
meaning, and publishing it invites a consumer to re-implement the threshold and
diverge from the validator.

**The forward rule, written now so P3 cannot get it wrong:** the moment `kg:`
becomes resolvable (§1.7), candidate lists must be filtered through
`db.canReadObject` *before* the list is assembled — not filtered after, not
counted before. A count, a score, a "N more" hint or a truncation marker computed
over unfiltered results is the same disclosure the uniform error closes.

### 4.5 Why `deferred_namespace` is `info`, not an error

The brief lists it in the error taxonomy, and it belongs there as a **code** —
consumers need to enumerate it — but its severity must be `info`, because a
program full of `db:` operands is a **correct phase-1 result**, not a failure.
Making it an error would mean `insert(db:products, dry_run=true)` — the plan's own
§3 example, which "must typecheck" — comes back invalid, and P2 would train the
model on a language in which its own primer is rejected.

`complete: false` and the `deferred[]` index are how a consumer distinguishes
"phase-1 valid" from "dispatchable" (§3.2).

---

## 5. Deferred validation

> **Decision D7 — deferred operands are first-class AST nodes with
> `kind: "deferred"`, plus a top-level `deferred[]` index. KEAP guarantees
> structural well-formedness and nothing else.**

**What KEAP checks for `db:` / `svc:` / `doc:`:**

1. The namespace token is one of the seven in the grammar's `ns` production.
2. The `dotted_id` matches `ident ("." ident)*` and respects the length bounds
   (§3.6).
3. If a bracket term is present it is non-empty and ≤ 128 characters.
4. The operand appears in a slot whose opcode declares that namespace
   (`namespaces` in §2.2) — otherwise `namespace_not_accepted`. This is the *only*
   semantic statement KEAP makes about a deferred operand, and it is a statement
   about the **opcode**, not the resource.

**What KEAP explicitly does NOT check, and must never learn to:** whether the
database/service/document exists; whether the caller may touch it; its schema;
its columns; its tenant. `db:`/`svc:`/`doc:` **do not exist in KEAP** (plan §4)
and there is no list of them anywhere in this repo. An implementer who feels the
urge to "just check the name is plausible" is one commit away from a hardcoded
list of databases in `server/cortex/`, which is the exact coupling the two-authority
split removed.

**The contract to Wing:**

- `deferred[]` gives `{ stage, operand, ns }` for every unresolved operand, so
  Wing does not re-walk the tree.
- `complete: false` whenever `deferred[]` is non-empty.
- `ast.pipeline.stages[i].operands[j].surface` carries the text verbatim; `id`
  and `resolvedName` are `null`. Wing fills them in phase 2 or rejects.
- A deferred operand that Wing cannot resolve is a **phase-2 error**, reported in
  Wing's vocabulary. KEAP never sees it and must never be asked to.

**`kg:`/`ent:` are NOT deferred.** They are *unresolved* — a different state, in a
different list (`scope.unresolved`), with a different code. Deferring them to
Wing would be a category error: Wing does not own the KEAP corpus and cannot
resolve them either. §1.7 is the path by which they become `resolved`, and it
does not route through Wing.

---

## 6. Mutating verbs and `dry_run`

Plan §5.3 requires `dry_run` to default on mutating verbs. The question is
whether `validate` **injects** the default into the AST or merely **reports** its
absence.

> **Decision D8 — validate REPORTS. It never writes a value into `params`. It
> publishes the computed default in a separate, clearly-labelled `effective`
> block, and Wing enforces it.**

Three reasons, in order of weight:

1. **Injection is unlogged normalization.** Plan §7 and review §5.3 are explicit:
   a normalizer must be *total and provably meaning-preserving*, and **every
   normalization must be logged beside the raw emission, or the corpus records a
   pipeline the model never produced**. Writing `dry_run: true` into `params`
   makes the AST diverge from the emission — and the AST is what P3 stores as
   training data. The corpus would then teach the model that it emitted a flag it
   never emitted, and the measured "validity rate" of P2 would be measuring the
   validator's edits.
2. **A flag in a document is not a guard.** The dry-run gate is an *execution*
   guarantee and belongs to the authority that executes. KEAP is not in the
   dispatch path; a defaulted field in a JSON body it hands over provides exactly
   as much safety as Wing chooses to grant it. Injecting it creates the
   *appearance* of a guarantee KEAP cannot make — the same failure mode as §1.6.2.
3. **`params` must stay a faithful record for drift analysis.** Distinguishing
   "the model emitted `dry_run=true`" from "the model omitted it and we defaulted"
   is exactly the signal P2 needs to measure whether the primer taught the flag.
   One field cannot carry both facts.

**The mechanism, in full:**

- Every stage carries `mutating: <bool>`, copied from the registry.
- For a mutating stage with **neither** `dry_run` nor `commit` present:
  `effective: { "dry_run": true }` + warning `mutating_default_dry_run`.
  `valid` stays `true`.
- For `dry_run=false` with no `commit`: `effective: { "dry_run": false }`. Still
  warned — the explicit false is the model's statement, and Wing's confirm-gate
  is what decides.
- For `commit=true`: warning `commit_requires_confirm_gate`. `valid` stays
  `true`. KEAP does not reject it, because rejecting a grammar-legal program on a
  policy KEAP cannot enforce teaches the model a rule that the executor does not
  actually implement.
- For a non-mutating stage: `effective` is `{}`.

**Wing's obligation, stated as a contract clause:** *Wing MUST NOT dispatch a
mutating stage whose `effective.dry_run` is `true`, regardless of `params`.
`effective` is normative; `params` is a record.* If Wing implements only one of
the two blocks, this is the one.

**kNN replay (P4) inherits this unchanged:** plan §6.1 — replay never bypasses
the dry-run gate at any confidence, and modifiers are never inherited from a
precedent. Because `params` is verbatim and `effective` is computed, a replayed
*shape* carries no `params` at all, and `effective.dry_run` recomputes to `true`.
The separation makes the rule mechanical rather than a discipline.

---

## 7. What P1 explicitly does NOT do

Named so the implementer does not drift into P2/P3.

1. **No execution, no side effects, no writes.** Not a row, not a proposal, not an
   embedding, not a log line that mutates state. `validate` is `agentAuth('ro')`
   and must remain safe to call in a loop.
2. **No LLM in the container.** Resolution is FTS5 + exact lookup. No classifier,
   no `embedText`, no Ollama call.
3. **No corpus, no precedents, no kNN.** `(input, pipeline, outcome, correction)`
   storage is **P3**, in its **own off-container store with its own index**
   (review §6.2 — a P0 decision, not a P3 one). P1 stores nothing, which is
   precisely why it cannot violate that boundary.
4. **No `kg:`/`ent:` resolution.** §1.4. Requires per-identity capability tokens
   (nOS-side) and, for `ent:`, an actual writer for `object_type_definitions`.
5. **No `db:`/`svc:`/`doc:` resource knowledge.** Ever. §5.
6. **No normalizer and no repairer.** Malformed input returns a typed
   `syntax_error` with a position. `@input.map(...)` is **not** rewritten to
   `@input | map(...)` — that is guessing intent (review §5.3). Test vector 13
   pins this.
7. **No AST → surface rendering.** Plan §7 renders the pipeline *from* the AST for
   humans; that is a P2 consumer concern and belongs where the AST is emitted.
8. **No control flow.** No `branch`, no nesting, no conditionals, no multiple
   pipelines per request. Plan §10 keeps the IR flat through P3.
9. **No `/agent/v1/context`.** Late binding is what demoted it from hard
   prerequisite to ambiguity fallback (plan §6.1). It is parallel work, and this
   endpoint must not grow into it.
10. **No enforcement of `dry_run`, `commit`, confirm-gates or idempotency keys.**
    Reported only (§6). Enforcement is Wing's.
11. **No authorization.** `scope.authorizes: false`. §1.6.2.
12. **No rate limiting or quota.** Named as a real gap (§1.6.5); bounded only by
    §3.6 input caps.
13. **No AST input.** `{ ast }` revalidation is P2 (§3.1).
14. **No bump of `contracts.selfmodel`.** `cortex: 1` is an **added** key.

---

## 8. Test vectors

These are the implementation's fixtures. Every input is grammar-consistent with
plan §3 — examples that do not typecheck become bad P2 training material.

Ids referenced are real in the seed spine (`src/game/data/taxonomy.ts`):
`01` = Natural Sciences, `01.01` = Physics, `01.01.01` = Classical Mechanics,
`01.01.01.01` = Kinematics, `01.01.01.01.01…05` = Motion equations / Projectile
motion / Circular motion / Relative motion / Reference frames.

> **Fixture discipline.** Unit tests (`server/cortex/*.test.ts`, vitest — **never**
> under `knowledge/`, that CI job installs `--ignore-scripts`) drive the tokenizer,
> parser and registry with no DB. Rows needing resolution use a temp data dir set
> **before** `await import('./db')`, per `server/relations.test.ts:13-16`. The e2e
> spec (`e2e/validate.spec.ts`, `Bearer e2e-ro`) must be **stateless** — it seeds
> nothing and cleans nothing, or it breaks `e2e/relations.spec.ts` and
> `e2e/ztopics-tenant.spec.ts`, whose assertions depend on exact corpus counts.

| # | Input `source` | Expected outcome |
|---|---|---|
| 1 | `@input \| classify(tax:01.01)` | **valid**, `complete: true`. 1 stage, `opcode: "classify"`, `mutating: false`. Operand `{ns:"tax", kind:"resolved", binding:"exact", surface:"01.01", id:"01.01", resolvedName:"Physics"}`. `errors: []`, `warnings: []` |
| 2 | `@input \| classify(tax:node[Kinematics])` | **valid**. Late binding resolves. Operand `{binding:"late", scopeHint:"node", surface:"Kinematics", id:"01.01.01.01", resolvedName:"Kinematics"}`. `surface` is the term, **not** the id |
| 3 | `@input \| classify(tax:01.01[Kinematics])` | **valid**. Same resolution, `scopeHint: "01.01"` — subtree-scoped search. Proves the scope hint of D6 narrows rather than filters after the fact |
| 4 | `@input \| classify(tax:node[motion])` | **error `ambiguous_operand`**, `detail: {ns:"tax", surface:"motion", candidates:[…]}` with ≥2 and ≤5 entries drawn from `01.01.01.01.01…04`, each `{id,name,path}`, **no rank/score**. `ast: null`. Nothing is chosen |
| 5 | `@input \| classify(tax:node[zzzqqxwv])` | **error `unknown_operand`**, `detail: {ns:"tax", surface:"zzzqqxwv"}` — the uniform one. No candidates, no "did you mean" |
| 6a | `@input \| get(kg:0f9c3e21-4b7a-4f2c-9d51-8ab6e0c72d13)` *(id does not exist)* | **error `namespace_not_resolvable`**, `detail: {ns:"kg", scope:"system-ontology"}` |
| 6b | `@input \| get(kg:<id of a real private object>)` | **byte-identical to 6a** after substituting nothing — `detail` contains no operand text. **No DB call is made.** This pair is the disclosure invariant (§4.3) |
| 7 | `@input \| insert(db:products, dry_run=true)` | **valid**, `complete: false`. Operand `{ns:"db", kind:"deferred", id:null, resolvedName:null}`. `deferred: [{stage:0, operand:0, ns:"db"}]`. Info `deferred_namespace` + `deferred_program`. `effective: {dry_run:true}`, **no** `mutating_default_dry_run` warning (it was explicit) |
| 8 | `@input \| link(rel:is-a)` | **error `unknown_operand`**, `detail: {ns:"rel", surface:"is-a"}`. The plan's own round-1 bad example; `is-a` is not one of the 16 |
| 9 | `@input \| link(rel:<a status='proposed' verb>)` | **error `unknown_operand`** — identical shape to row 8. `'proposed'` rows are agent-plantable and are not operands |
| 10 | `@input \| link(rel:requires)` | **valid**, warning `mutating_default_dry_run`, `effective: {dry_run:true}`. Pins that `MECHANICAL_VERBS` is a *suggestion* filter, not a validity filter |
| 11 | `@input \| delete(db:products)` | **valid: true**, warning `mutating_default_dry_run` (`detail:{opcode:"delete"}`), `effective: {dry_run:true}`, `params: {}` — **`params` stays empty; the default is never injected** (§6) |
| 12 | `@input \| map(tax:01.01` | **error `syntax_error`**, `offset: 22`, `length: 0`, `detail: {found:"<eof>", expected:[")", ","]}`. Exactly one error entry |
| 13 | `@input.map(tax:01.01)` | **error `syntax_error`**, `offset: 6`, `detail: {found:".", expected:["\|","<eof>"]}`. **Not** rewritten to `@input \| map(…)` — §7.6 |
| 14 | `@input \| frobnicate(tax:01)` | **error `unknown_opcode`**, `detail: {opcode:"frobnicate", didYouMean: []}`. Suggestions are drawn only from the published registry |
| 15 | `@input \| classify()` | **error `arity_error`**, `detail: {opcode:"classify", min:1, max:1, got:0}` |
| 16 | `@input \| classify(db:products)` | **error `namespace_not_accepted`**, `detail: {opcode:"classify", ns:"db", allowed:["tax","kg"]}`. Grammar-legal namespace, wrong verb — distinct from a deferred operand in an accepting slot (row 7) |
| 17 | `@input \| classify(tax:Nos.Services)` | **error `malformed_operand`**, `detail:{ns:"tax", surface:"Nos.Services", reason:"id shape"}`. Uppercase fails the canonical regex; **no lookup is attempted**, so a shape-illegal id cannot probe existence |
| 18 | `@input \| classify(tax:orphan.dropped)` *(a `taxonomy_nodes_ext` row that `registerExtNodes` dropped)* | **error `unknown_operand`** — identical to row 5's shape. `getNode` is the only oracle; the row on disk must not resolve |
| 19 | `@input \| insert(db:products, ?hidden=true, dry_run=true)` | **valid** (plan §3's headline example). `params.hidden = {value:true, defaulted:true}`, `params.dry_run = {value:true, defaulted:false}`. The `?` form is preserved, not flattened |
| 20 | `@input \| classify(tax:node[Kinematics])` *with `taxonomy_fts` empty* | **error `late_binding_unavailable`**, `detail:{ns:"tax", reason:"index unavailable"}` — **never** `unknown_operand`. Distinguishes "search is broken" from "no such term" |
| 21 | `@input \| classify(tax:node)` | **error `malformed_operand`**, `reason:"reserved scope word requires a term"` (D6) |
| 22 | *(any valid program)* | `ast.binding` carries `ontologyVersion` matching `GET /agent/v1/health → ontology.version`, `databaseId` matching `database.id`, `opcodeRegistryHash` matching `GET /agent/v1/validate/opcodes → registryHash`, and `expiresAt - validatedAt === ttlSeconds * 1000` |

---

## 9. Implementation map (non-normative)

| concern | file |
|---|---|
| request/response contract (zod envelope only) | `shared/contracts/cortex.ts` |
| hand-written LL(1) tokenizer + parser | `server/cortex/parse.ts` |
| frozen opcode registry + `registryHash` | `server/cortex/opcodes.ts` |
| operand resolution + namespace policy | `server/cortex/resolve.ts` |
| ontology fingerprint (D4) + cache invalidation | `server/cortex/ontology-version.ts` |
| report assembly | `server/cortex/validate.ts` |
| routes `POST /agent/v1/validate`, `GET /agent/v1/validate/opcodes` | inside `registerAgentRoutes`, `server/agent.ts:120` |
| `contracts: { selfmodel: 1, cortex: 1 }`, `ontology.version` | `server/agent.ts:133` (**add keys, never bump `selfmodel`**) |
| OpenAPI entries | `OPENAPI_SPEC`, `server/agent.ts:1171` (hand-maintained, no parity test, but mcpo/Open WebUI enumerate from it) |
| unit tests | `server/cortex/*.test.ts` (vitest) |
| e2e | `e2e/validate.spec.ts` — stateless, serial, `Bearer e2e-ro` |

**Gate note for whoever implements this:** the real typecheck is
`npx tsc -p tsconfig.server.json --noEmit` (or `npm run typecheck`). Root
`tsconfig.json` has `files: []` and does not include `server/`, so `npx tsc
--noEmit` exits 0 no matter what is written there. Lint is frozen at
**0 errors / max 31 warnings**; a hand-written tokenizer is exactly the code that
trips `@typescript-eslint/no-unused-vars` (an **error**, only `^_` ignored) and
`no-explicit-any` (a warning).
