# The routing address — a capability-addressed work graph (`dtt-routing-address`)

Design spec. Operator idea (2026-09-04, `docs/plans/datatables-subsystem.md` §15);
four grammar forks resolved by the operator 2026-09-05. This is the spine of
**nos-planner** and, expressed the other way, of the **access model**
(`dtt-share-model`). Design-first: this document + a reference parser/matcher
(`tools/nos_work_uri.py`, the executable definition); the planner implements
against it in its own language.

## 1. The grammar

A work address is a real, routable URI — greppable in logs, glob-queryable, one
parser everywhere (fork #4: real `nos-work://`, not a notation):

```
nos-work://<WHERE>/<WHO>/<KAM>/<CO>/<KDY>
```

| segment | meaning | vocabulary | composes with |
|---|---|---|---|
| **WHERE** | execution locus | `local` · `eu-cloud` · `ext-cloud` · `*` | cloud/local tiers, ADR-0003 network boundaries |
| **WHO** | principal | `agent:<name>` · `user:<canonicalUid>` · `*` | `identity.md` + `dtt-share-model` principal vocabulary |
| **KAM** | access/target scope | `repo` `dtt` `keap` `cortex` `internet` `fs:<dir>` `all` · scoped verbs `keap.read` `dtt.write` · `*` | the tool/scope model |
| **CO** | task_type | a slug from `state/task-types.yml` · `*` | `dtt-task-types` |
| **KDY** | when | a date `YYYY-MM-DD` (deadline) · `@<pulse-job>` (trigger) · `*` (anytime) | Pulse |

Every segment is a **set** (fork #2: KAM — and uniformly all of them), joined by
`+`, or `*` for "any". A segment value is `[A-Za-z0-9_.:@/-]` (so `fs:documents`,
`keap.read`, `agent:minimax` are single values).

## 2. Two readings of one address (fork #1: BOTH, planner matches)

- **Capability** — what a principal MAY do. Held by an agent (its
  `dtt-share-model` grant, expressed as an address):
  `nos-work://local/agent:minimax/repo+dtt/code-fix/*`
  = "MiniMax, running locally, may do `code-fix` work touching the repo and
  DataTables, anytime."
- **Assignment** — what a `currentState` row NEEDS:
  `nos-work://local/*/repo/code-fix/2026-09-10`
  = "a `code-fix` on the repo, must run local, due 2026-09-10, any agent."

The planner **matches** assignments to capabilities. `dtt-share-model` and this
are the same fact from two sides: an ACL grant IS a capability address.

## 3. The match — `assignment ⊆ capability`

An assignment is satisfiable by a capability when, for each structural segment
(WHERE, WHO, KAM, CO), the assignment's need is **covered** by the capability's
grant. `*` on either side means "any" for that segment.

- **WHERE** (hard, fork #3): the assignment's locus must be in the capability's
  grant. `assignment=local` needs `capability ⊇ {local}`. `assignment=*` means
  the planner may place it anywhere the capability allows (the planner fills the
  gap). A hard requirement (private data → `local`) is expressible and enforced;
  it is never silently relaxed.
- **WHO**: if the assignment names a principal it must equal the capability's;
  `*` = any agent, planner picks.
- **KAM**: the assignment's target set must be a **subset** of the capability's
  (`assignment=repo+dtt` needs `capability ⊇ {repo,dtt}`). A scoped verb
  (`keap.read`) is covered by the bare scope (`keap`) but not vice versa.
- **CO**: the assignment's `task_type` must be in the capability's set (or `*`).

**KDY is not a subset match — it is scheduling.** The deadline/trigger is a
constraint the planner satisfies (run before the date, on the Pulse trigger),
within the capability's availability window. It selects *when*, not *whether*.

So the planner's core query is a glob over held capabilities:

```
find a capability C such that  assignment ⊆ C   (segment-wise, per §3)
then schedule within KDY.
```

## 4. Why URI-real matters

The address lands verbatim in audit trails and Pulse rows, so "who can do WHAT
on WHERE touching KAM" is a `grep`/glob, not a join — matching the estate's
"detectors read artifacts" doctrine:

```
grep 'nos-work://local/[^/]*/repo/' audit.log     # everything local touching the repo
```

## 5. What this is NOT (scope guard)

- Not a second RBAC store — it is a **projection** of `dtt-share-model` grants
  into an address. The ACL rows remain the source; the address is the queryable
  view (and the planner's match key).
- Not a scheduler — KDY names the constraint; Pulse runs it.
- Not built here — this is the grammar + reference matcher. The planner
  (`face-planner` / `nos-planner`) builds the UI and the live matcher against
  `tools/nos_work_uri.py` and its tests.

## 6. Open, deferred deliberately

- ~~The **capability source**~~ **RESOLVED 2026-09-06 (share-model zod landed
  in v1.44.0): a DERIVED PROJECTION**, not a second store. `tools/agent-
  capability.py` derives each agent's address from its manifest — WHERE from
  the `-cloud` naming, WHO from `name`, KAM from `tools:` (plus `internet` when
  the effective model is hosted), CO from an authored `task_types:` list (the
  one segment nothing else declares, operator call — kept minimal, governed
  like the enum). The dtt slice of KAM reconciles against share-model grants.
  KAM's vocabulary is the **tool-scope namespace** (repo, dtt, keap, cortex,
  wing, bone, loop, internet, fs:<dir>), of which the grammar table above
  listed an excerpt; the
  parser constrains its shape, not its membership. A tool-less local agent
  (the ops-* measurement subjects) holds no external scope and no routing
  capability — reported, never emitted as a malformed address. Gate:
  `tests/anatomy/test_agent_capability_projects.py`.
- **fs:<dir>** granularity vs the VFS tree (`fs` epic) — a KAM value like
  `fs:tenants/<t>/shared` should reuse the filesystem doctrine's paths.
- A capability with a **set WHERE** (an agent that may run local OR eu-cloud) —
  supported by the grammar (`local+eu-cloud`); the planner's placement optimizer
  within that set is a nos-planner concern.
