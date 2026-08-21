# 19 — Fable review of the agentic-loop engine, second pass

*One slow pass, synthesised from three adversarial lenses. Measured against HEAD `a5d025c8`
(dev) and the live `~/wing/app/data/wing.db`, 2026-08-21. The first pass is
[13-fable-review.md](13-fable-review.md) (2026-08-19, HEAD `5d83e384`); this one does not
supersede it — §2 notes that all three of its asks landed.*

## 1. Verdict

**Sound-with-changes** — the separations are real code at four layers and the mechanism turns, but
for the proposal class that dominates its output the verdict cannot yet vary with the thing being
judged, so what runs today is a ledger with a ceremony attached, not a closed loop.

## 2. What is already right

The four-identity split is not prose. `loopauth.py` issues distinct scopes, `ledger.py:314` puts
`CHECK (actor = 'engine:judge-runner')` on every verdict row, no route ACCEPTS a result (§3.1), and
`tools/loop-review.py:41-45` holds a forge credential with no propose scope. Two lenses went looking
for a seam between proposer and verdict; neither found one.

Three more, once each. **Blast radius**: `main.py:296-321` mounts the reader and the judge/ledger
routes in separate try/except blocks, so a loop import error cannot take `/api/v1/events` down
mid-converge. **Anti-duplication**: `red-status.py:319-357` loads `loop-status.py::awaiting()`
rather than re-deriving "is this patch in the tree". **Refusal over automation**: the
committed-evidence deadlock is surfaced (`loop-status.py --gap`) and refused (`loop-propose.py` exit
3) rather than dissolved by auto-committing evidence, which would let the loop mint its own
retry-ceiling keys. And `budget.py:453-511` judges the artifact in both directions;
`weaknesses.py:154-160` makes an unattributed self-report unconstructable; the previous pass's three
asks all landed — a review loop that visibly closes is evidence the doctrine is live.

## 3. The three changes worth making

### 3.1 Make the verdict discriminate for version-pin diffs — `state/judge-sets.yml`

Measured: `wordpress_version: 9.9.9-nonexistent` passes the `repo` set 3868/0. That set is
ansible-lint + genome-codegen + pytest-anatomy (`judge-sets.yml:296-308`); none reads a version
value, and `.woodpecker/tests.yml` pulls no image. Three of four merged diffs are version bumps, so
for those three `pass` carried zero information and correctness came entirely from the queue's
`fix_version` — which nothing validates and which CLAUDE.md records being wrong in the dangerous
direction once (REM-178 vs REM-137).

Two parts, cheap half first. **(a) Record vacuity distinctly**: when no judge in the set has an
`oracle_paths` overlap with the diff, the verdict is `nothing objected`, not `pass` — one hour, and
the gap becomes visible on every surface. **(b) A `pin-resolves` judge**: registry manifest HEAD, no
pull, no live estate. Its objection is real (a network call inside a deterministic oracle); the
answer is that a lookup failure is INDETERMINATE, never pass.

### 3.2 `_source_pulse_runs` must honour `findings_exit_codes` — `weaknesses.py:1324-1396`

Its SQL joins nothing (`WHERE exit_code IS NOT NULL AND exit_code <> 0`), so it emits
`pulse:discovery:contradiction-scan … exited 1` for a job that declares `findings_exit_codes: [1]`
(`plugins/discovery/plugin.yml:97`) and filed a roadmap row. `red-status.py:137-157` learned this on
2026-08-20 and suppresses it. Two readers of one signal now disagree about one fact on the live
estate — which red-status's own comment calls worse than either being wrong alone. And worse than a
false positive: severity ratchets to HIGH at streak ≥ 3 (`weaknesses.py:1373`), and the loop's own
nightly job declares `findings_exit_codes: [1, 3]` (`plugins/loop-base/plugin.yml:86`) where exit 3
is the deadlock the contract says recurs on the scan's cadence. Three such nights and the loop mines
itself as a HIGH weakness its own `files/anatomy/bone/**` deny rule forbids it from proposing
against.

### 3.3 One declaration of "proposable", with a reason — `weaknesses.py`

"What may the loop work on" is computed three times: `evidence_committed` per source,
`loop-status.py:656-658`'s withheld remedy, and `loop-propose.py:72-75`'s `UNFIXABLE_SOURCES`. They
disagree. Of 60 withheld rows, 6 (3 git, 1 alert, 2 pulse) carry `evidence_committed=False`
unconditionally, so the single printed remedy — "commit it to unblock" — is unsatisfiable for all
six. Separately `rank()` puts git-worktree first (`weaknesses.py:1404-1419, 1532-1546`), so live
`?top=10`, which `skills/weakness-scan/SKILL.md` consumes, opens with three rows that close by `git
commit` and are not expressible as `diff_text`. Expose `proposable` + `proposable_reason` on the
projection; both tools read it.

*Ranked out, correct and cheap*: amending DECISION 6 to permit read-only in-repo Python import (the
code already deviates at `loop-status.py:175-180`, and the code is right); marking the Hermes
reproducibility claim aspirational; one `events` row per verdict (today: zero).

## 4. What to stop

**Stop compensating for the nine fixture rows, and stop being able to write them.** 9 of 21 rows in
`loop_proposals` are `w1`/`w2` — ids no source can emit — and every surface reporting on the loop
carries a permanent exclusion clause to hide them; `loop-status.py` prints the disclaimer twice in a
five-line report. But "delete the nine rows", as one lens asked, is not executable, and here I
correct both: `w1` has **8** verdicts and `w2` **1**, `loop_verdicts` is hash-chained with
`loop_verdicts_worm_delete` (`ledger.py:353-365`), so deleting them trips the trigger or breaks the
chain — the exact property §3.2 buys. Executable form: **point the gates at a temp DB now** (that is
the subtraction, and the write that should never have happened), then offer the operator a one-time
recorded chain re-genesis — the chain is three days old and its value entirely future-facing, so
this is cheap today and impossible in practice in a year. If declined, the exclusion is permanent
debt and belongs in one place.

Nothing else. The retired M7 `_FileLock` machinery (`judges.py:761-1318`) is pinned unused by
`test_the_engine_judges_its_own_gates.py:66-81`, so keeping the primitive costs nothing and
re-declaring it is caught — a considered no, not an omission.

## 5. The strongest objection

Two were offered and they are not equal, so I pick. The weaker: *"5460 lines against Bone's ~3880 —
a fifth organ that entered as a module."* It loses on its own lens's refutation: organ boundaries
are deploy unit and blast radius, not line count, and the loop adds no process, no port, no launchd
unit, no `state/manifest.yml` row and so no derived route.

The real one: **the loop is aimed at the easy third of the backlog.** Three of four merged diffs are
one-line version bumps whose correctness lives in a field written by a different agent; a sed script
and thirty seconds of attention produces the same three commits. What would actually improve this
estate is out of reach by construction — hidden fees close by writing `docs/**`, denied at
`budget.py:134`; alerts and pulse rows carry `evidence_committed=False` permanently; git rows close
with a commit. Five of seven sources have never produced a proposal.

**I concede the aim and refuse the sed.** The proposal space today IS the remediation queue plus one
freshness row, and the design documents read broader; say so in the contract. What the sed lacks is
one address answering "did this tree pass" identically from Pulse, from CI and from a model, plus a
memory making the second attempt at a bad idea free to detect — and a proposal has already been
refused before a human saw it (7p/2f/2i across 11 rem proposals). But the objection lands on §3.1,
which is why §3.1 is first.

## 6. Least sure

**Whether `pin-resolves` is the right shape, or whether a version bump's correctness belongs
upstream in whatever writes `fix_version`.** A judge that reaches a registry can be wrong for
reasons unrelated to the diff, against a standing rule about oracles depending on what they measure.
What settles it: run the four merged diffs back through a prototype probe and count. Zero of four →
the signal belongs in the queue writer and the vacuity half of §3.1 is the whole change. One → it
belongs in the gate set and the argument is over.
