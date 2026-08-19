# 13 — Fable review: the agentic-loop engine

One slow pass over `files/anatomy/bone/*.py`, `state/judge-sets.yml`,
`docs/idea/11-agentic-loop-contract.md` and the readers around them. Everything below was
run against the live estate on 2026-08-19, HEAD `5d83e384`.

## 1. Verdict

**Sound-with-changes** — the separation the design rests on is real and enforced in three
independent layers, and every change worth making is in the *bookkeeping around* the engine.

## 2. What is already right

- **The proposer/judge split is code, not prose.** `loopauth.py:61-66` issues three
  identities (`agent:proposer` → propose, `engine:evaluator` → judge, `operator` → forget);
  `ledger.py:314-316` puts `CHECK (actor = 'engine:judge-runner')` on every verdict row;
  `seal_verdict` (`ledger.py:1108-1109`) takes `gate_set` plus an optional `proposal_uuid`
  and nothing else — no result, and no run-selection argument, because selection is forgery.
  `check()` (`ledger.py:872-876`) derives the §6.2 lift key instead of accepting it.
- **`aggregate()` refuses the estate's own hidden fee.** `judges.py:1005-1012` returns
  INDETERMINATE for an empty judge set, naming `all([]) is True` as hidden-fee-08 sitting
  inside the aggregator written to detect it. The `min_work` ratchets
  (`state/judge-sets.yml:100-172`) record why each floor moved.
- **The budget checks the artifact in both directions.** `budget.py:494-511` refuses a
  declaration claiming *more* than the diff touches, because `target_paths` is a §4
  fingerprint input and padding it mints a fresh ceiling for byte-identical bytes.
- **The readers are honest.** `tools/red-status.py` surfaced today's two stalled proposals
  unprompted. I looked for a reason to call the core unsound and did not find one.

## 3. The three changes worth making

### 3.1 Rewrite the §11 proof criterion — `docs/idea/11-agentic-loop-contract.md:716-727`

§11 adopts the parent's criterion unchanged: *"a weakness that was on the list, is not on
the list."* The architecture forbids satisfying it. `budget.py:134` is
`Rule("docs/**", "doctrine", "§5.2")`, and 63 of the 69 weaknesses live today (50
remediation rows under `docs/llm/security/`, 13 hidden fees under `docs/hidden_fees/`) can
only leave the list via a write under `docs/`. State the reachable criterion: the loop makes
the **diff** that closes the weakness, an operator converges, the **scanner** retires the
row — and the verdict replays.

Half an hour. First because §9 names nine deliberate non-decisions and this is not among
them, so a reader takes it as reachable; and the cheapest way to "fix" it is to carve a hole
in `docs/**`, the one rule standing between the loop and its own doctrine.

### 3.2 Give the ledger a "passed, awaiting an act outside the loop" state — `files/anatomy/bone/ledger.py`

Measured in `~/wing/app/data/wing.db`: proposal `6f139e22` (`rem:REM-204`) holds two sealed
`pass` verdicts, 2026-08-16 and 2026-08-19; `default.config.yml:1357` still reads
`wordpress_version: "7.0.2"`; the row is still `pending`, still ranked `high`. `rem:REM-159`
sits at attempt 2 of `DEFAULT_MAX_ATTEMPTS = 2` (`ledger.py:119`) with an unchanged
`weakness_evidence_sha`, so `check()` now answers `fingerprint-exhausted`. The loop cannot
tell a weakness it solved from one it never touched, so it spends both attempts and parks
the item permanently at the head of the list.

Here I pick rather than average. One lens asked for this state; another asked instead to
**bound re-judging** of an already-sealed proposal (`judges.py:148` parses `deterministic`
and nothing reads it). The bound alone loses: `tools/red-status.py` prints `[re-judge]`
today as the recommended action for both stalled proposals, and re-judging is exactly what
happened to `6f139e22` and changed nothing — refuse it without recording what the proposal
waits for and a wasteful loop becomes a silent dead end. Do the state first; the bound
follows from it, and `deterministic` gets a consumer or a deletion. While in the file, say
which verdict is *the* verdict: `tools/loop-status.py:315-318` already invented
`ORDER BY id DESC LIMIT 1` because nothing said.

### 3.3 Make `rank()` yield to actionability — `files/anatomy/bone/weaknesses.py:1532-1546`

`rank()` keys on the `SOURCE_ORDER` index first and severity second, and `git-worktree` is
first (`:1404-1409`). Live `?top=10` leads with three `git-worktree` rows (two of them the
nightly scan's own uncommitted writes), then `rem:REM-159` (exhausted) and `rem:REM-204`
(already passed). Five of the ten slots the skills consume
(`skills/weakness-scan/SKILL.md:17` calls `?top=10`) are structurally unproposable: a
`git-worktree` finding is fixed by `git commit`, which is not expressible as a `diff_text`,
and `tools/loop-status.py` confirms `git` has never been proposed against. The morning after
a nightly scan is the expected steady state, not an edge case. §9.1 leaves ranking open, so
this is *not yet* rather than a defect — but it is an hour's work and doubles the window.

## 4. What to stop

**Stop writing test fixtures into the operator's live ledger.** 9 of 13 `loop_proposals`
rows in `~/wing/app/data/wing.db` carry `weakness_id` `w1`/`w2` — ids no source in
`SOURCE_ORDER` can emit — and `tools/loop-status.py` renders them as peers, so its headline
reads `13 proposal(s)` when 4 are real and `1p/7f/0i` of `w1` dominates the only surface
that answers "is the loop working". Point them at a temp DB.

Also stop chasing §11 as written in **either** direction while 3.1 is pending: do not relax
`docs/**` to satisfy it, and do not read the current failure as the loop not working.

Nothing in the engine itself should be removed. I looked.

## 5. The strongest objection

*"You have found the design working. The queue is written by the scanner. If the loop could
mark `rem:REM-204` resolved it would be recording its own success against a weakness it
selected, judged by a gate set that cannot see the change — the v0.10-beta self-reporting
defect rebuilt inside the machine built to refuse it. `Rule('docs/**', …)` is the doctrine
holding."*

**Conceded, as to the wall.** `docs/**` stays shut. The honest chain is propose → verdict →
merge → converge → rescan → retire; five of its six links belong outside the loop, and a
loop contributing one link of six is still a loop.

**Not conceded, as to the memory.** Recording "this proposal passed and awaits an external
act" is not the proposer grading itself: the verdict came from `engine:judge-runner` under a
CHECK constraint, and the state asserts nothing about the weakness — only the proposal. The
wall is right, the sign painted on it is wrong, and the loop needs a memory of what it is
waiting for.

## 6. What I am least sure about

**Whether a `pass` from gate set `fast` carries any information about a version-pin diff.**
`fast` is `ansible-lint` + `genome-codegen` (`state/judge-sets.yml:270-272`); neither reads
a version *value*, and `grep -rlE "_version.*==.*['\"][0-9]+\.[0-9]+" tests/anatomy/`
returns nothing, so `repo` may not either. If so, one word `pass` covers both "eight fixture
proposals genuinely failed here" and "no judge could see the change" — and a constant reward
signal is the condition under which a proposer's optimisation goes somewhere unintended. Not
in the top three only because "sensitive to this diff" is not decidable in general.

**What would settle it:** submit `wordpress_version: "9.9.9-nonexistent"` and run gate set
`repo` against it. If it seals a `pass`, the signal is empty for the proposal class that
dominates the list, and that labelling work moves to the top of §3.
