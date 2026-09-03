# The two loops — sequence doctrine

> Status: doctrine, opened 2026-08-21. This file is the estate's only statement
> of the *sequence* — which step hands to which, holding which identity,
> refusing what. Component behaviour stays owned by the artifacts cited on each
> edge; where this file and a cited gate disagree, the gate wins and this file
> is the bug. Section numbers are stable. The verified Mermaid diagrams and the
> full narratives live in
> [`docs/loops-companion.md`](../loops-companion.md), under the same numbers —
> this file keeps the rules, the refusals and the missing-edge ranking.

## 0. Why this file exists

On the night of 2026-08-20→21 the loop ran unattended for the first time and
an unjudged proposal fell between `loop:propose` and `loop:drive`: **nothing
joined the step that makes a proposal to the step that lands one.** The gap
survived a full day of attended use because a human judged every proposal
within a minute of filing — a person was silently an edge in the graph.
(Closed `f3b34a19`; full account: companion §0.)

The general defect is the reason this document exists: **this estate has a gate
for every node and almost none for the edges.** Judges, ledger, weakness
reader, budget, driver, reviewer, cadence — each was built and pinned in
isolation, and each of those gates is genuinely good. No artifact stated the
sequence, so no gate could notice a missing step. This file states it; §7 ranks
the edges still missing; §8 says what an *edge gate* is and which to write
first.

## 1. Two loops, and where they touch

Two loops, not one, and they are not the same thing (overview diagram:
companion §1):

- **SERE** — the self-enhancing loop: the estate improving its own SOURCE.
  Weakness → proposal → judgement → merge request → review → `dev`. It ends at
  the trunk, on purpose: converging source into runtime and retiring the
  weakness are the business loop's and the operator's, never SERE's
  (`docs/idea/11-agentic-loop-contract.md` §11 — "the loop contributing one
  link of six is still a loop").
- **The nOS loop proper** — the estate serving its purpose: knowledge (KEAP /
  cortex), agents, the Pulse cadence, the notification event→state path,
  backup, the security pipeline, identity/SSO, the face.

**Where they must NOT touch** (each refusal is enforced, not prose): SERE may
not edit its own oracle, engine, doctrine, secrets, edge surface
(`budget.py`, contract §5.2; gate `test_loop_budget_forbids_its_own_gates.py`).
It never merges to `master` (`_refuse_master` in both driver and reviewer),
never pushes GitHub (`PROMOTE_ARGV = ["--apply"]`, never `--push-github`),
never converges, never runs a removal, and never touches the per-session
AgentKit iteration loop (`agent_iterations` — a different loop, §7 non-goal 1).
The engine has no routable surface at all — loopback Bone routes, no manifest
entry (REM-144 doctrine).

## 2. SERE — the proposal state machine

Every state below is derived, not stamped: the ledger is the record of what
arrived, `git apply --check` (forward and reversed) is the oracle for
landed-ness, and no step writes its own success (`tools/loop-status.py` header;
contract §3.5). Four credentialed identities traverse it — proposer, engine
judge-runner, driver/evaluator, reviewer — plus the operator; §4 maps them.
(State-machine diagram: companion §2.)

**The refusal edges are the design.** Verified refusals, each observed live or
pinned: the engine accepts no verdict from anyone (`POST /loop/verdicts` does
not exist — contract §3.1); a 403 across identities is the boundary working; a
409 names the offending path or the retry ceiling; the driver refuses `master`,
a desynced base (both directions — the 598 KB MR and its quieter inverse), an
unreachable forge ("not an empty one"), and a branch tip it cannot prove it
made (`_owns_remote_tip`, two proofs); the reviewer touches only `fix/loop-*`,
refuses on any NO, and *waits* on any INDETERMINATE — an unanswered question is
not a yes. A malformed patch is `unusable`/`indeterminate`, never `fail`: a bad
patch is not a bad idea (`tools/loop-diff.py` moved the format burden off the
model for exactly this).

**Two things the diagram marks dashed because they are true:** the
landed→converged edge and the converged→retired edge belong to the operator
and the scanner by design — but *neither wait has a per-item surface yet*
(§7.2, §7.3). And the withheld→pick unblock is a human commit with no cadence
(§7.5): the entry half deliberately runs at 01:30, *before* the 02:00 scan
re-dirties the queue (`43a6dd08`), so it sees the tree as the operator left it
— an ordering that is load-bearing and currently declared nowhere a margin
analyzer can see (§7.4).

## 3. The unattended night — the cadence as a clock

The night's sequence — 01:30 propose, 02:00–03:30 security scans, 04:15–05:30
KEAP/cortex chain, 06:00 drift watch, 06:10 drive, 06:50 review — plus the
business-loop clock around it: companion §3. The load-bearing facts are the
*order* and the *margins*, not the wall times; the loop chain having **no
declared temporal edges** while the KEAP chain has five measured ones is a
finding (§7.4), not a style note.

## 4. Identities — who holds what, who may call what

Three credential channels exist estate-wide (`docs/doctrine/identity.md` §3);
the loop's channel is `IDENTITIES` in `files/anatomy/bone/loopauth.py` and it
is the one drawn in companion §4. All may read; none may do another's job; a
403 across a boundary is the boundary working.

The generalised rule (`loop-review.py` header): **whoever writes a change may
not bless it, and no step records its own success.** The proposer proposes and
stops; the driver judges and lands and stops; the reviewer merges and stops;
whether anything LANDED is git's answer read back by `loop-status.py`. Wing
`/pulse` pause/unpause is an operator surface; a manifest may withdraw only a
pause whose reason is byte-identical to the one it declared (`72b909e3` —
gate `test_a_manifest_clears_only_its_own_pause.py`).

Operator acts the loop may never perform, enforced not promised: `forget`
(scope on a token no automation holds), `dev → master` (refused in code +
server ruleset), GitHub push (argv pinned), non-beta tags, removals
(`tools/nos-stacks.sh` refuses every removal token), converge.

## 5. The nOS loop proper — the estate serving its purpose

The business loop is many small loops sharing three organs: **Pulse** (the one
scheduler), **Wing** (the one record), **Bone** (the one loopback API). The
organ diagram, grouped by what each serves: companion §5.

What refuses what, business side (each verified in source): Pulse refuses
shell interpreters, relative paths, secret-shaped env inheritance and
un-allowlisted args — **twice**, at registration and at spawn; a job's secrets
are `secret:` pointers resolved at exec time, never values in the row; an
unresolvable pointer is a synthetic rc=255, not a run with a literal. The
notification path's floor is `[wing-inbox]` — nothing is ever fully silent —
and the reconciler refuses to mark read anything whose evidence it cannot read
(exit 2 so the suppression rule itself announces it). The scan runner
fail-closes a scan that did not run (`scan_failed`, never fabricated
freshness). `deploy-from-ci.sh` never escalates; sudo-touching tags are
rejected by Wing before it is spawned. Every reader is a reader
(`test_the_red_reader_only_reads.py`, `test_the_identity_reader_only_reads.py`)
— a reader that could repair would end up certifying its own repair.

**Where this loop is genuinely right, and worth saying so:** the event→state
split (a notification is an event, red is a state; the suppression rule plus
`red-status` plus the evidence-driven reconciler form a coherent triangle
rather than three patches); the BFF projection ("the place where the upstream
response stops" — a new secret-bearing column upstream cannot reach a browser
by default); success markers written by readers, estate-wide; and the backup's
member-count emptiness gate paired with a restore drill that replays rather
than lists. These are node-solid. The weaknesses are, again, edges: the LLM
scan producer feeding an ungated artifact into everything downstream, and the
two agent runtimes that never meet.

## 6. The evidence graph — which artifact proves which claim

The estate's standing rule (CLAUDE.md, 2026-08-01): *success markers are
written by a reader, not by the attempting code* — pytest owns shape, `--tags
verify` owns effect, `nos-smoke --strict` owns end-to-end truth, and none may
claim another's job. This is the question→reader→artifact join; a question
with no reader is how the unattended night happened. (The eight-question
diagram: companion §6.)

Two properties hold across all eight, and both are doctrine rather than
accident: every reader exits 0 whatever it finds (a fact about the estate must
not be a build failure caused by nobody's commit), and every unreadable source
is UNKNOWN, never green. `tools/nos-cc.sh` re-runs these as panes — state, not
scrollback. The verdict chain adds a ninth answer no reader can fake:
`nos-loop verdict --replay` re-runs the recorded argv against the recorded
tree and reproduces the recorded exit, work count and stdout hash — a verdict
that cannot be replayed is a claim.

## 7. Missing and weak edges, ranked

Ranked by what each would cost tonight, unattended. #0 is kept first as the
archetype even though it is closed. Full accounts per item: companion §7.

0. **propose → drive** (`unjudged` fell between the steps) — **CLOSED
   2026-08-21** (`f3b34a19`), exercised the same afternoon.
1. **`requires_operator` is stamped and consumed by nobody.** Neither
   `loop-pr.py` nor `loop-review.py` reads the column (contract §5a: "never
   auto-accepted"). **MISSING refusal edge**; cost = the loop's one
   explicitly-forbidden automation, performed silently.
2. **landed → retired: the queue does not learn from a converge.** The
   scanner is the only retirement writer; twelve rows were already LIVE at
   their fix version, and REM-178 found a recorded fix *below* what runs.
   `discovery:contradiction-scan` sees part of it and may only file.
   **WEAK** — surfaced, not joined.
3. **The post-merge waits have no standing state.** An INDETERMINATE MR and
   a merged-but-unconverged item both look like day one to every reader —
   waiting indistinguishable from done. **MISSING reader.**
4. **The cadence order is enforced by two cron numbers and nothing else.**
   `pulse:loop:*` are orphan nodes in `state/anatomy-graph.json` — zero
   `depends_on`, zero temporal edges — while the KEAP chain carries five
   measured margins. **WEAK.**
5. **The withheld-evidence unblock is a human edge with no owner.** The
   ledger (correctly) withholds `rem:` rows until someone commits the scan's
   writes; surfaced everywhere, owned nowhere. **WEAK**: the entry half
   starves on any day the operator forgets.
6. **The security producer is an LLM writing an ungated artifact.** No
   schema or cross-field gate validates `remediation-queue.json` /
   `scan-state.json`; the freshness corroborator is a spot check, not a
   contract. **WEAK**.
7. **AgentKit and Pulse never meet** (`runner: agent` is schema-only; the
   bound loop is measured unproven —
   `test_the_bound_agent_loop_is_unproven.py`). Deliberate and documented, so
   **TARGET** rather than defect.
8. **The restore drill replays 2 of ~8 source classes** (keap-db, wing-db);
   the off-site restic copy has never been restore-verified. **PARTIAL**:
   cost appears exactly once, at the worst possible time.

## 8. Edge gates — what they are, and the first three

A **node gate** pins a component's behaviour against its own spec. An **edge
gate** pins a *join*: it enumerates what the producer can emit and proves the
consumer accounts for every element — or that a refusal stands where
consumption must not happen. The unattended night in these terms: the ledger
could hold a proposal in a state (`unjudged`) that no downstream selector
included, and no gate asserted the selector covers the producible set. Node
gates on both sides were green throughout; the join had no owner. (The two
gates written with `f3b34a19` are the estate's first true edge gates; the
pattern generalises.)

Worth writing first, in order (fixtures and retro-verification: companion §8):

1. **The unattended path refuses `requires_operator`** — closes §7.1, the
   only edge whose absence violates an explicit contract clause.
2. **Every ledger state has an owner** — the generalisation of `f3b34a19`:
   every producible state is consumed by a named actor or declared terminal
   with a reason.
3. **The cadence chain is declared, and its margins are measured** — closes
   §7.4 with machinery that already exists (`depends_on` + the margin
   analyzer, exactly as the KEAP chain).

## 9. Toward a derived ontology

This file is hand-drawn and STATIC on purpose — the sequence needed stating
once, by a person, with the false edges left out. Most of what it draws is
already data (`tools/anatomy-graph-gen.py` → `state/anatomy-graph.json`); the
derivation target — two new edge kinds, `handoff` and `identity`, inside
`anatomy-graph-gen`, same artifact, same gate, same apex ruling — is companion
§9. When those edges become data, the diagrams become checkable against the
graph and this file shrinks to the prose and the refusals, which is what
doctrine is for.
