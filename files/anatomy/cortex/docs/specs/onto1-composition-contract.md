# The `onto1:` composition contract

Status: **normative.** P-2 of the cortex backend/UI split
(`../nOS/docs/plans/cortex-backend-boundary-decision.md` §6a). Written against
KEAP v1.26.0.

**Reference implementation:** `knowledge/onto1-compose.mjs` (plain ESM, no server,
no database, no TypeScript).
**Conformance suite:** `knowledge/onto1-conformance.mjs` + `knowledge/fixtures/onto1/`.
**Agreement proof:** `server/onto1-agreement.test.ts` — KEAP's runtime and the
reference implementation must produce a byte-identical serialization over the
live tree.

## 0. Why this document exists

`ast.binding.ontologyVersion` is what tells a dispatcher *"the ontology moved,
revalidate"*. Two implementations that compose the same git data differently
produce **different fingerprints from identical input** — and then each side
rejects the other's ASTs while both believe they are correct. The failure is
silent, total, and indistinguishable from a genuine ontology change.

So the composition cannot remain "whatever `server/taxonomy.ts` happens to do".
This is that behaviour, written down, with a fixture set to be graded against.

Everything below is normative. Where the prose and
`knowledge/onto1-compose.mjs` disagree, **the fixtures decide** — they are the
executable form of this document.

## 1. Inputs

Three, all readable from git except the third's status column:

| input | source | shape |
|---|---|---|
| **spine** | `knowledge/spine/*.json`, read in **file-name order** | `{ key, category }` per domain |
| **grown rows** | `taxonomy_nodes_ext` | `{ id, parentId, name }`; `parentId` `''`/null marks a user root |
| **relation types** | `relation_types` (SoT: `knowledge/ontology/relation-types.json`) | `{ type, status, label }` |

File-name order is not cosmetic. The composition walks the domains in that
order, which fixes every parent's child sequence. The fingerprint sorts and so
does not depend on it — **the UI and the U1 layout bake do**.

Descriptions are an input to nothing here (§3.3).

## 2. Composing the node set

### 2.1 The spine

Walk each domain document depth-first: the category, then its `subcategories` in
object-key order, then its `items` in array order. Each node contributes
`{ id, parentId, name }`, where **`parentId` comes from nesting, never from
parsing the id.** The two agree today (`knowledge/lint.mjs` gates it), but the
composition is defined structurally so a future id scheme cannot silently
reparent the tree. A category's `parentId` is `null`.

### 2.2 Grown rows register as a fixpoint

A row registers only once its parent is present. Iterate the pending set
repeatedly until a pass registers nothing, to a bound of
**`MAX_REGISTRATION_PASSES = 12`**.

One pass is not enough and the difference is not theoretical: rows arrive in
`created_at` order, not ancestry order, so a subtree whose children were created
before their root would be dropped **in silence** — the exact defect that shipped
once and was fixed in v1.21.0. `case-02-fixpoint` pins it.

Iteration order *within* a pass does not affect the resulting node set, and
therefore does not affect the fingerprint. (KEAP iterates the pending array in
reverse; a port need not.)

### 2.3 An existing id wins, and the row is consumed

If a grown row's id is already present, the existing node **is kept unchanged**
and the row is **removed from pending** — it is *not* reported as dropped.

This matters twice: an implementation that lets the grown row overwrite produces
a different `name` and therefore a different fingerprint from identical input;
one that leaves the row pending reports a spurious drop. `case-04-collision`
pins both.

### 2.4 Roots

A row with an empty `parentId` is a **user root** iff its id matches
`^[a-z][a-z0-9-]*$`. Otherwise it does not register.

Seed domains are two-digit numerals, so the id spaces are structurally disjoint —
there is no reserved range to remember. The shape test is what distinguishes a
deliberate root from a row whose parent silently failed to resolve;
`case-03-orphans-and-roots` pins all three rejections.

A registered root has `parentId` `null`.

### 2.5 Dropped rows

Rows still pending when the fixpoint stops are **dropped**: they contribute
nothing to the fingerprint. A conforming implementation reports them (KEAP logs
a warning naming up to five). The fingerprint describes **the vocabulary the
validator actually used**, not a superset that exists on disk.

## 3. The canonical serialization

Two record kinds, each a **tab-joined** line. All node records precede all verb
records. Lines are joined with `\n` and there is **no trailing newline**.

### 3.1 Node records

```
t <TAB> id <TAB> parentId|"-" <TAB> name
```

One per composed node, ordered by `id` **ascending by UTF-16 code unit** — i.e.
plain `<`/`>` comparison, **not** `localeCompare` and not a numeric-aware sort.
A root's `parentId` is the literal `-`.

Code-unit ordering is load-bearing: `'Alpha' < 'alpha' < 'zeta'` because `A` is
`0x41` and `a` is `0x61`. Any locale-aware collation disagrees on some real id.
`case-05-verbs` pins it on the verb half, where the effect is visible.

### 3.2 Verb records

```
r <TAB> type <TAB> status <TAB> label
```

One per verb whose `status` is `seed` or `confirmed`, ordered by `type` with the
same collation. **`proposed` is excluded** — any RW bearer can plant one by
POSTing an unknown type to `/agent/v1/relations`, so admitting it would let an
agent move the fingerprint.

`label` is included and is not decoration: `resolveVerb` matches a bracket term
against it in both the exact and the substring tier, and writes it into
`operand.resolvedName`. A label edit is therefore resolution-affecting, and
`knowledge/ingest.mjs` upserts labels from the checked-in SoT on every run — so
an editorial change could flip `rel:verb[…]` from a unique bind to
`ambiguous_operand` while the fingerprint stayed still, and the
"version moved → revalidate" rule would never fire.

### 3.3 What is deliberately excluded

`description`, `zone`, `path`, `kind`, `childIds`.

`description` is the notable one, and the exclusion is a **named, accepted cost**:
K1 curated overrides churn editorially, and invalidating every stored precedent
on a wording fix costs more than it buys. The consequence — a description edit
can shift an FTS ranking without moving the version — is the one place this
fingerprint is deliberately coarse. A port must exclude it too; including it
would be "more correct" and would still be **wrong**, because it would disagree.

Strings are recorded **verbatim**: not trimmed, not case-folded, not Unicode-
normalised. `case-06-unicode-and-tabs` pins that, and pins UTF-8 as the digest
encoding. The tab-joined form assumes names contain no tab character.

## 4. The digest

```
onto1:<first 16 lowercase hex chars of sha256(canonical, "utf8")>
```

## 5. Scope and lifetime

The fingerprint is **boot-scoped**, and correctly so. The in-memory tree is built
once at startup, while `knowledge/ingest.mjs` writes `taxonomy_nodes_ext`
straight to the database file and relies on a restart. Between the two,
resolution answers "unknown" for ids that exist on disk — and the fingerprint
describes the tree the validator used. **An AST records what it was checked
against, not what another process believes.**

Implementations should compute it fresh rather than memoise. The seams that
would need invalidation (`registerExtNode`, `registerExtNodes`,
`insertProposedRelationType`, `setRelationTypeStatus`, `seedRelationTypes`) sit
in modules the fingerprint imports, so a cache introduces a genuine import cycle
— and a stale fingerprint is not a slow answer, it is a **wrong** one asserting
"nothing moved" to the component whose whole job is to notice that it did.
Measured cost in KEAP: 0.18 ms over the 790-node spine.

## 6. Conforming

```
node knowledge/onto1-conformance.mjs
```

An implementation conforms iff, for every fixture in
`knowledge/fixtures/onto1/`, it reproduces **both** the exact canonical
serialization and the digest. Both are checked, and that is deliberate: two
hashes that differ tell you nothing about which field stopped mattering. The
canonical string is the diagnostic; the digest is the assertion.

A port in another language reimplements this document and compares against each
fixture's `expected` block — it does not need to execute the runner.

| fixture | what it pins |
|---|---|
| `case-01-minimal` | record shape, the `-` root sentinel, code-unit id order |
| `case-02-fixpoint` | children-first rows must all land (§2.2) |
| `case-03-orphans-and-roots` | the three rejections and the one valid slug root (§2.4) |
| `case-04-collision` | spine wins, and the row is consumed not dropped (§2.3) |
| `case-05-verbs` | `proposed` excluded; status and label recorded; collation (§3.2) |
| `case-06-unicode-and-tabs` | verbatim strings, UTF-8 into the digest (§3.3) |

The fixtures' expected values are generated by the reference implementation,
which would be circular on its own. The circle is broken by
`server/onto1-agreement.test.ts`: KEAP's runtime — an independent implementation
that composes through the in-memory tree rather than from git — must produce a
byte-identical serialization over the live 790-node spine, over 793 nodes with a
children-first grown subtree, and must agree on which rows were dropped.

## 7. What this contract does *not* cover

- **Child ordering.** `childIds` sequence is UI/layout behaviour (§1), not part
  of the fingerprint. A port that only serves `validate` need not reproduce it; a
  port that also serves the explorer must.
- **Zone assignment.** Derived from depth for spine nodes, stored per-row for
  grown ones — an asymmetry that is real but invisible here.
- **Descriptions and K1 overrides** (§3.3).
- **The ANN index and its parameters.** Configuration, not contract — and the
  current defaults are ~50× oversized, so a port should choose better ones and
  gate the change with `scripts/recall-gate.mjs`.
