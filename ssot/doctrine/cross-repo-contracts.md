# Cross-repo contracts — how nOS and a sibling repo agree on a shared surface

nOS produces surfaces that another repo consumes (today: the KEAP self-model —
nOS emits a knowledge tree, KEAP ingests and renders it). Each repo has its own
release train, its own agent, and its own opinion. This file is the protocol for
keeping them honest with each other.

A contract is something that can go red. Measured: nOS emitted nine `_stack.md`
files with one near-identical sentence; KEAP embedded them into nine vectors
that became top recall hits for unrelated physics queries. Neither side was
wrong about its own half — there was no shared artefact that could fail.

## 1. The three artefacts

1. **The spec** — one document, one physical location, cited by both repos.
   A local copy MUST NOT exist: two copies diverge, and the contract is
   whichever copy you happened to read. Carries `contract_version: N`.
2. **The fixture** — a small, committed, representative sample of the surface,
   owned by the PRODUCING side. Not a description of the shape: the shape
   itself.
3. **Symmetric gates** — the producer asserts *"I still emit this fixture"*;
   the consumer asserts *"ingesting this fixture yields what I promised"*.
   Both MUST run in their own CI, against the same bytes.

Symmetry is the whole design. A gate on one side only makes that side the
authority and the other side the supplicant; then drift is discovered by a
human noticing something looks wrong on a live map.

## 2. Peer rules

- **No hierarchy.** Neither agent assigns work to the other. Each states what
  it needs, what it will provide, and what it refuses — and expects to be
  argued with. "The other side asked for it" is not a reason to build
  something.
- **Objections are first-class.** Either side MAY object to any clause. An
  objection is a claim plus its evidence (file:line, a measurement, a failing
  case), and it MUST block the version bump until answered on the merits —
  answered, not overruled.
- **Neither side edits the other's half.** The producer MUST NOT rewrite the
  consumer's assertions to make its gate pass, and vice versa. Fix the
  surface or renegotiate the clause.
- **Disagreement is the point.** The two agents see different failure modes:
  the producer knows what its generator can guarantee, the consumer knows
  what its ingest actually does with it. A contract both sides agree to
  instantly is usually one neither side has tested.

## 3. Changing the contract

1. Raise it as an objection or a proposal, with evidence, in the spec's open
   items.
2. The other side answers on the merits.
3. On agreement: bump `contract_version`. Both gates and the fixture MUST
   update **in the same change**. A version bump with one gate updated is the
   failure this protocol exists to prevent.
4. Record the decision and the reasoning — including what was rejected and
   why. The next agent inherits the conclusion but not the argument, unless
   it is written down.

## 4. Invariants a contract must carry

Every shared surface MUST pin at least: **identity** (what makes a thing the
same thing across a re-emit — a stable key, not a hash of something
incidental), **visibility** (a produced item that silently fails to render is
worse than one that errors), and **removal** (what the consumer does when the
producer stops emitting something).

Those three are where drift hides, because none of them fails loudly on its
own.

## 5. Live contracts

| Surface | Spec | Producer | Consumer |
|---|---|---|---|
| nOS self-model → knowledge tree | `nos-keap:docs/specs/nos-selfmodel-keap-contract.md` | nOS (`files/anatomy/scripts/keap_selfmodel_gen.py`) | KEAP (`server/fs-sync.ts`, `knowledge/ingest.mjs`) |

## 6. Agreed, authoring pending — the DataTable engine (`tables`)

The **second** contract, and the first pointing **KEAP → nOS**. Agreed
2026-09-05; three objections were accepted. It is NOT in the Live table yet
because a contract is something that can go red, and its gates are not
written. Spec + gates author on the operator's go — the store/doors spec
**after** the `dtt-share-model` zod, so the visibility invariant cites a
real module, not a promised one.

**The measurement that made this a re-labelling, not a refactor:** 38
DataTable DEFINITIONS live in nOS git (`state/keap-tables/*.table.yml`, gated
by `test_keap_table_concepts.py`); 29 of them are SYSTEM (estate tables nOS
emits); 9 are fixture/user-shaped (`print-*`, `kolben-*`) — tenant-demo
furniture that happens to live in git, not KEAP-born USER tables. Zero
definitions are KEAP's; every row-store consumer is nOS. KEAP PROVIDES the
store, the two doors, row history, ref integrity, and card/graph
materialisation. The arrow is already backwards — so the honest step is
publishing the contract, not moving the engine (whose cost — `syncCard`/
`syncRows`, Authentik-tier visibility, ref integrity, all in KEAP's libsql —
is not worth paying for legibility alone; the move stays a later,
separately-triggered decision).

**Two halves.** (a) DEFINITIONS `nOS → KEAP`: nOS emits the SYSTEM/code-declared
`.table.yml`; KEAP loads/validates. Producer nOS. (b) STORE + DOORS `KEAP → nOS`:
KEAP serves `/api/tables` + `/agent/v1/tables`; nOS consumes (roadmap tools,
McpTablesTool, dtt-capture, apps_runner, face). Producer KEAP.

**The three clauses (the objections, kept because each names an incident):**

1. **System vs user tables (definitions scope).** The definitions half covers
   only the code-declared SYSTEM tables (the 29). USER tables are KEAP-born (the
   human door mints them, `POST /api/tables`), never in nOS git, governed by the
   doors half + `dtt-share-model` — and EXPLICITLY outside the definitions
   contract, so a definitions-side gate MUST NOT prune a table nOS did not
   emit. The `print-*` / `kolben-*` defs are in git so schema-pin still sees
   them; they are fixture-shaped, not SYSTEM. Mirrors the `dtt` §14.3
   system/user split.
2. **Schema-pin gate (highest value).** The definitions-side gate validates
   every git-owned `.table.yml` against KEAP's zod schema **at the pinned
   `keap_repo_ref` (`v2.0.0-rc.1`)** (a vendored schema snapshot pinned to the
   tag, never dev HEAD). This makes "a definition runs ahead of the pin"
   structurally impossible instead of a matter of release discipline — the
   `caddy-sessions` incident (`style: chat` against a schema only an orphan tag
   carried; a dev-cut release would have 400'd the seed and killed the
   converge, uncaught offline) is what it prevents.
3. **Removal = the definition lifecycle, not just `onDelete`.** The contract
   names the reconcile classes — options-only changes reconcile silently;
   destructive changes (dropped column, kind change) 409 and require the
   operator-gated drop-and-recreate ceremony (export rows → delete → re-POST →
   re-insert) — and forces a sentence on what a definition⇄live divergence
   leaves the system in. **Recorded exception:** `roadmap.table.yml` dropped
   `when` (successors: `target` / `occurred_at`). The live table still has
   `when`; reconcile 409s on that drop, and nothing seeds roadmap, so the
   successor definition never lands. MUST NOT drop-and-recreate the live table
   to close this — that ceremony is operator-gated, not a docs fix. The
   exception stays until that ceremony runs.

**Invariant triple** (4): IDENTITY = the row `__id` + `assertRowId`,
DRIVER-enforced (KEAP `70027be`) — a structural guarantee, not a route
convention; VISIBILITY = references `dtt-share-model` (the grade/tier model),
MUST NOT be duplicated; REMOVAL = clause 3 above.

**Behaviour changes the store/doors spec MUST record** (both pinned this
week): upsert merge treats `null` as *delete-the-cell*; object/table update
*merges* rather than replaces.

**Authoring split:** KEAP authors the store/doors spec in `nos-keap:docs/specs/`
(producer-owned), indexing the door gates already written (`row-id-guard`,
`row-null-clear`, `agent-row-identity`, `agent-table-search`, `row-claims`,
`rowref-contract`, `table-schema-reconcile`). nOS drafts this registry row's
promotion to Live + the definitions-side schema-pin gate (clause 2). Both on the
operator's go; on completion this entry moves into the Live table above.
