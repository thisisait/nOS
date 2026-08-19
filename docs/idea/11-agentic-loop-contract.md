# 11a — The agentic loop: engine contract

**Status: contract settled, not built.** Opened 2026-08-02.
**Parent:** [11-agentic-loop.md](11-agentic-loop.md) — the shape. This document is
the **contract**: what gets built, where it lives, and what it may not do.

Every section states a **DECISION**. §9 lists what was deliberately *not* decided.
Where this contract contradicts the parent document, the contradiction is marked
**DEVIATION** and justified — the parent is a sketch, and three of its choices do
not survive contact with the measured judges.

---

## 0. What was measured before deciding

Nothing below is inferred from documentation. The load-bearing claims were run.

| # | claim | command | result |
|---|---|---|---|
| M1 | `genome-codegen --check` is a real gate | `python3 tools/genome-codegen.py --check` after appending a comment to `nos_entity.py` | `STALE generated artifacts: …` **EXIT=1**; restored → `genome artifacts current (2 checked)` **EXIT=0** |
| M2 | `nos-smoke` reads absence as success | `python3 tools/nos-smoke.py --include zzz-nonexistent-service --no-jsonl` | `smoke catalog yielded zero entries` **EXIT=0** |
| M3 | `pytest-anatomy` reads absence as success | `env -u WING_API_TOKEN HOME=/tmp/emptyhome python3 -m pytest tests/anatomy/test_hub_url_audit.py -q -rs` | `2 skipped` **EXIT=0** |
| M4 | Bone already executes subprocesses | `grep -n 'subprocess\|run-tag' files/anatomy/bone/main.py` | `POST /api/run-tag` → `subprocess.Popen`; `apply-detached` → backgrounded run |
| M5 | Bone is already off the edge | `roles/pazny.traefik/vars/main.yml:151` | `traefik_skip_ids: [bone, cortex, …]` — bone published 127.0.0.1 only |
| M6 | WORM triggers are bypassable | `tests/anatomy/test_audit_chain.py:188` | `con.execute("DROP TRIGGER events_worm_update")  # simulate an offline attacker` — the estate's own test does this |
| M7 | `genome-codegen` and `pytest` collide | `tools/genome-codegen.py:49` vs `test_genome_contract.py` | both write `files/anatomy/module_utils/nos_entity.py` |

M2 and M3 are the same defect as
[`docs/hidden_fees/08-empty-stack-reads-as-success.md`](../hidden_fees/08-empty-stack-reads-as-success.md),
in the judges themselves. **The loop's judges currently contain the exact failure
mode the loop exists to detect.** That is the single most important input to this
contract, and §2.4 is built on it.

---

## 1. WHERE IT LIVES

> ### DECISION 1 — The engine is **new modules inside Bone**, not a new daemon.
> No new process, no new port, no new launchd/systemd unit, no new manifest entry.

New files, mounted on the existing FastAPI `app`:

```
files/anatomy/bone/
  loop.py        # routes  (/api/v1/loop/*)
  judges.py      # judge registry + adapters + sandbox
  ledger.py      # schema, chain, the ONLY verdict writer
  budget.py      # path budget computed from the gate set
```

### Why not a new daemon

**Constraint E is free in Bone and costly in a new thing.** Bone binds
`127.0.0.1:8099` (`bone.plist.j2`) and is already listed in `traefik_skip_ids`
with a justification a test can read (M5). A new daemon means a new
`state/manifest.yml` entry, and the moment that entry carries `domain_var` +
`port_var` it auto-derives a Traefik router —
`tests/anatomy/test_traefik_exposure_justified.py` exists because exactly that
happened to Traefik's own dashboard and leaked the password prefix (REM-144). The
cheapest way to satisfy E is to add no routable surface at all.

**The judge is not a new capability class in Bone.** Bone already shells out:
`POST /api/run-tag` runs `ansible-playbook`, and `apply-detached` backgrounds an
upgrade that survives the operator's session (M4). Running `pytest` is strictly
less privileged than running the playbook. In a new daemon, subprocess execution
would be the daemon's whole reason to exist and would need its own hardening
review, its own scope model, and its own audit path — three things Bone has.

**The ledger's home is already Bone's.** Bone writes `events` to `wing.db`
(`WING_DB_PATH` in the plist) and owns `migrations.py`. The ledger is three more
tables in a database Bone already opens.

**Long-running judges have a precedent here.** `pytest-anatomy` is 190 s. Bone
already solved "a request that outlives the caller" with `apply-detached`.

### The one real argument against Bone, and its answer

Bone's operational routes require an **Authentik-issued JWT** (`auth.py`). The
loop must return the same verdict at 03:00 during a blank, in CI, and on a host
where Authentik is down — a judge that depends on the stack it judges is not a
judge.

This is not a new problem and Bone already answered it. From `auth.py`:

> The `/api/v1/events` telemetry sink keeps its bare-hex HMAC contract. […] the
> callback fires inside ansible-playbook runs, where Authentik may not be up —
> making it depend on JWT would create a bootstrap dependency on the very stack
> we're observing.

The judge has **identical** bootstrap properties.

> ### DECISION 1a — Loop routes authenticate on a third channel: a loopback-only
> bearer token, independent of Authentik. Not JWT, not HMAC-over-body.

Two tokens, not one (see §3.4), both minted random and persisted (§8, constraint D).

### DEVIATION from the parent

Parent §3 says "a small host daemon, sibling to Bone/Pulse/Cortex". **Rejected.**
Sibling-by-default is how an estate acquires its fifth organ; the parent's own
constraint H ("reuse, do not rebuild") points the other way, and the sibling buys
nothing Bone lacks.

Routes are namespaced `/api/v1/loop/*` to match Bone's existing `/api/…` prefix,
not the parent's bare `/v1/…`.

---

## 2. THE JUDGE CONTRACT

### 2.1 The registry is data, and it is committed

> ### DECISION 2 — Judges and gate sets are declared in `state/judge-sets.yml`,
> committed to the repo. Not in code, not in the plugin, not in `~/.nos`.

A gate set must mean the same thing in CI, on the operator's Mac, and in a 03:00
Pulse job. A set defined in runtime state can drift per host; a set defined in
the repo is diffable and is itself covered by the budget (§5 forbids editing it).

Each judge declares, as fields a test can read:

```yaml
judges:
  ansible-lint:
    argv: ["ansible-lint"]
    adapter: exit_zero          # 0 = pass; 2 = fail (NOT 1 — measured)
    pass_exit: [0]
    fail_exit: [2]
    deterministic: true
    runtime_s_p95: 55
    work_field: files_processed # parsed from the terminal line
    min_work: 1400              # RATCHET — see §2.4
    mutates_worktree: false
    requires: []
```

`min_work` is a **ratchet in the style of `BLAST_RADIUS_CEILING`** — it records
today's reality so scope cannot silently shrink. The measured note on
`ansible-lint` flagged that only 1400 of 2977 encountered files are processed and
*"nothing pins that ratio, so silent scope loss would read as green"*. This field
is that pin.

### 2.2 The five adapters — because exit codes disagree

Verdicts are **never** read from a bare exit code. Each judge names an adapter.

| adapter | verdict rule | judges using it | why not exit code alone |
|---|---|---|---|
| `exit_zero` | 0 = pass, listed non-zero = fail, anything else = INDETERMINATE | ansible-lint (fail=**2**), genome-codegen (fail=1) | ansible-lint's failure code is 2; a naive `!= 0` check is right by accident and a naive `== 1` check is wrong |
| `exit_count` | 0 = pass, 1..126 = fail with N failures | nos-smoke | exit *is* the failure count, capped at 127 — not a boolean |
| `json_field` | parse stdout JSON, read a named boolean | corpus-diff (`.agrees`) | **exit 0 while the report says DISAGREE** — the exit code is not the verdict |
| `pytest_summary` | parse `N failed, M passed, K skipped` | pytest-anatomy | exit 0 covers "all skipped" (M3) |
| *(none)* | — | keap-lint | **rejected as a judge**, §2.6 |

### 2.3 Aggregating a set

> ### DECISION 2a — A set is PASS **iff every judge in it is PASS**. Any FAIL →
> FAIL. Any INDETERMINATE with no FAIL → INDETERMINATE. No majority, no
> weighting, no "mostly green".

Three-valued, not two. The third value is the whole point of §2.4.

### 2.4 Fail closed: absence is never success

This is the section the measurements paid for. Three of five judges return **0**
when they did no work (M2, M3, and corpus-diff's `night VOID` when the organ is
unreachable — where, note the asymmetry, incumbent-down is red but organ-down is
green).

> ### DECISION 2b — Every judge reports a **work count**. A verdict whose
> `work_count == 0`, or whose `work_count < min_work`, is **INDETERMINATE** —
> never PASS. INDETERMINATE blocks acceptance exactly like FAIL.

INDETERMINATE is recorded *distinctly* from FAIL so that a broken judge is never
mistaken for a broken proposal. Conflating them would teach the loop to "fix"
proposals in response to an unplugged organ.

> ### DECISION 2c — A judge whose `requires:` are absent returns INDETERMINATE
> **before running**. It never runs degraded.

`requires` is explicit per judge: `live_estate`, `keap_token_ro`,
`cortex_token_ro`, `docker`. corpus-diff requires **both** tokens *and* both
organs reachable; if the cortex organ is down it is INDETERMINATE, correcting the
script's own `night VOID → 0`.

This single rule closes M2, M3, and the corpus-diff asymmetry with one mechanism
rather than three patches.

### 2.5 Side-effecting judges

> ### DECISION 2d — `pytest-anatomy` runs **only** in an ephemeral git-worktree
> sandbox, always — attended and unattended alike. If the sandbox cannot be
> created, the judge is INDETERMINATE. It is never run against the live tree.

The question offered "sandbox **or** declare read-only-unsafe and exclude from
unattended cycles". Sandbox, for both, because the exclusion alone is unsafe *and*
insufficient:

`tests/anatomy/test_genome_contract.py` appends `HAND_EDITED = True` to the
**tracked** file `files/anatomy/module_utils/nos_entity.py` and restores it in a
`finally`. If the run is killed — timeout, OOM, SIGKILL, the normal failure mode
of an unattended loop — the tracked source is left corrupted. Excluding it from
unattended cycles leaves the corruption risk on every *attended* run, which is
when the operator is most likely to have uncommitted work. And M7: that file is
also `genome-codegen`'s output target, so the two judges corrupt each other.

Corollaries, both enforced by the engine:

- **The engine refuses to run `pytest-anatomy` and `genome-codegen` concurrently**,
  and refuses either concurrently with itself. Same file, no lock upstream.
- **Every judge runs against the sandbox tree when a proposal is under judgment**,
  so the verdict describes the *proposed* tree, not the operator's working copy.

> ### DECISION 2e — Judges are invoked with their side effects suppressed by flag,
> and the flags are part of the committed `argv`.

`nos-smoke` → `--no-jsonl` (measured: otherwise appends to `~/.nos/events/smoke.jsonl`,
outside the repo, where `git status` can never reveal it).
`cortex-corpus-diff` → `--no-ledger --json` (measured: otherwise advances or
zeroes `agreeStreak`, may page the operator via A9, and may run `--halt-cmd`,
stopping the organ's fs-sync). **A judge that can page the operator and halt an
organ is not a judge.**

### 2.6 keap-lint is rejected as a judge

> ### DECISION 2f — `keap-lint` is **not** in any gate set. It stays a Pulse job.

Measured from its own header: it requires `KEAP_AGENT_TOKEN_RW`, POSTs
`/agent/v1/lint/run` which *"reconciles state"* — a write to the corpus — and
fans results into the A9 notification path. Its exit contract is
*"0 ran (with or without findings)"*: the exit code carries no verdict at all.

That is a scheduled maintenance job with an alerting side effect, not a
deterministic oracle. Admitting it would give the loop a judge that mutates the
thing being measured.

**DEVIATION:** the parent says "the six judges above, each already exists". Five
of the six are judges. The sixth is a job.

### 2.7 The named gate sets

| set | judges | runtime | requires | unattended |
|---|---|---|---|---|
| `fast` | ansible-lint, genome-codegen | ~57 s | none | yes |
| `repo` | `fast` + pytest-anatomy *(sandboxed)* | ~250 s | clean tree for sandbox | yes |
| `live` | nos-smoke, cortex-corpus-diff | ~3 s | live estate + 2 RO tokens | yes |
| `full` | `repo` + `live` | ~255 s | all of the above | attended only |

`fast` is the only set with no repository-mutating judge and no live dependency;
it is the default for a first cycle.

---

## 3. THE LEDGER, AND CONSTRAINT A IN SQL

### 3.1 The primary control is not SQL

The question offered three options: separate write tokens, a `CHECK` constraint
on an actor column, or an append-only trigger. **All three are defence in depth,
and none is the primary control**, because the estate has already proved its own
WORM triggers bypassable — `tests/anatomy/test_audit_chain.py:188` does
`DROP TRIGGER events_worm_update  # simulate an offline attacker` (M6). On a
single-UID host, a proposer with shell can drop any trigger and rewrite any row.
Claiming otherwise would be the kind of decorative gate constraint C forbids.

What actually stops a proposer choosing its verdict is architectural:

> ### DECISION 3 — There is **no endpoint that accepts a verdict**.
> `POST /v1/verdicts` is deleted from the design. A verdict row is written only
> by `ledger.py`, only inside the judge runner, only as a byproduct of a
> subprocess having actually exited.

**DEVIATION:** the parent's §3 table lists `POST /v1/verdicts` — "record the
deterministic outcome … evaluator writes, proposer cannot". An endpoint that
accepts a verdict and distinguishes writers by credential is a lock whose key is
a header. Removing the input surface removes the class: *you cannot forge a value
you are never asked to supply.* The only verdict-producing route is
`POST /api/v1/loop/judge`, which takes a **gate set name** and returns whatever
the subprocess returned. There is no field in any request body, anywhere in the
API, that influences a verdict's result.

### 3.2 The schema

Three tables in `wing.db` (reuse — constraint H: Wing already has the chain
discipline, the ALTER sweep, the backup path and the UI).

```sql
CREATE TABLE IF NOT EXISTS loop_proposals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid           TEXT NOT NULL UNIQUE,
    fingerprint    TEXT NOT NULL,              -- §4
    content_fp     TEXT,                       -- §4, normalized-diff hash
    weakness_id    TEXT NOT NULL,
    intent_class   TEXT NOT NULL,
    gate_set       TEXT NOT NULL,
    target_paths   TEXT NOT NULL,              -- canonical JSON, sorted
    tree_sha       TEXT NOT NULL,              -- git rev-parse HEAD at propose time
    proposer_id    TEXT NOT NULL,              -- 'agent:<name>' | 'operator'
    proposer_model TEXT,
    attempt_n      INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS loop_judge_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid         TEXT NOT NULL UNIQUE,
    proposal_id  INTEGER,                      -- NULL = bare judge run
    gate_set     TEXT NOT NULL,
    judge_name   TEXT NOT NULL,
    argv         TEXT NOT NULL,                -- exact, incl. --no-jsonl etc.
    sandbox_path TEXT,
    status       TEXT NOT NULL,                -- running | exited | crashed
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    exit_code    INTEGER,
    work_count   INTEGER,
    stdout_sha   TEXT,
    stdout_head  TEXT                          -- bounded evidence excerpt
);

CREATE TABLE IF NOT EXISTS loop_verdicts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid         TEXT NOT NULL UNIQUE,
    proposal_id  INTEGER,
    gate_set     TEXT NOT NULL,
    result       TEXT NOT NULL CHECK (result IN ('pass','fail','indeterminate')),
    actor        TEXT NOT NULL CHECK (actor = 'engine:judge-runner'),
    tree_sha     TEXT NOT NULL,
    evidence     TEXT NOT NULL,                -- JSON: per-judge run uuids
    prev_hash    TEXT,
    row_hash     TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Plus WORM triggers modelled on `events_worm_update` / `events_worm_delete`
(`files/anatomy/wing/bin/init-db.php:401`), firing only on chained rows
(`OLD.row_hash IS NOT NULL`), and a `row_hash = sha256(prev_hash ‖ canonical_row)`
chain reusing `App\Model\AuditChain`'s discipline.

### 3.3 Why this cannot be bypassed by the thing it constrains — stated exactly

Honest, layered, and bounded:

1. **Through the API: impossible, not merely forbidden.** No route accepts a
   result. The proposer's token (§3.4) carries `nos:loop:read` +
   `nos:loop:propose` and reaches no route that writes to `loop_verdicts`.
2. **Through a stray SQL client: refused twice.** `CHECK (actor = 'engine:judge-runner')`
   rejects any insert that names another writer, and the WORM triggers reject
   UPDATE/DELETE on a chained row.
3. **Through an offline attacker with the DB file: detected, not prevented.**
   Triggers can be dropped (M6). The hash chain makes the tampering *evident* —
   the same guarantee `verify-audit-chain.php` already provides, where a tampered
   chain verifies as BROKEN (exit 2).
4. **The actual guarantee is reproducibility.** Every verdict stores `tree_sha`,
   the exact `argv`, `exit_code`, `work_count` and `stdout_sha`. `nos-loop verdict
   --replay <uuid>` re-runs the identical command against the identical tree and
   compares. A forged verdict survives inspection only until someone replays it,
   and replay is cheap for `fast` (57 s).

**What is NOT claimed:** filesystem-level separation between proposer and judge.
On a single-UID macOS host, a proposer with shell has the same file permissions
as Bone. Putting the ledger in a separate DB file would not change that, which is
precisely why this contract does *not* pay the duplication cost of a separate
database for an illusory boundary.

### 3.4 Two identities, never one

> ### DECISION 3a — The proposer and the evaluator hold **different tokens with
> different scopes**, and the proposer's token cannot trigger a judge.

| identity | scopes | may |
|---|---|---|
| **proposer** (`agent:*`, the model) | `nos:loop:read`, `nos:loop:propose` | read weaknesses + budget + history, record a proposal |
| **evaluator** (Pulse job, operator CLI, the plugin's judge skill) | `nos:loop:read`, `nos:loop:judge` | trigger a judge run |

Constraint A says they "never share an identity". This is that sentence at the
credential level, not in prose. The ceremony is: the proposer proposes and stops;
the **driver** — a distinct process holding a distinct token — triggers judgment.

### 3.5 Constraint B: no step records its own success

`loop_judge_runs` is written **before** the subprocess starts, with
`status='running'`. It is completed by the code that *reads the process's exit*,
not by the judge. A judge that is killed leaves `status='running'`; a sweep at
next boot marks such rows `crashed` → the set is INDETERMINATE, never PASS.

`work_count` is parsed from the subprocess's own stdout, never supplied by a
caller. `result` is computed from `exit_code` + `work_count` by the adapter, never
accepted as input. This is the shape of
`tests/anatomy/test_post_wiring_is_not_self_reporting.py`, applied to the engine
that is supposed to enforce it.

---

## 4. PROPOSAL FINGERPRINTING

> ### DECISION 4 — Two fingerprints, with different jobs.

**`fingerprint`** — "the same attempt at the same thing":

```
fingerprint = sha256(canonical_json({
    "weakness_id":  "REM-137" | "hidden-fee:08" | "pytest:tests/anatomy/x.py::test_y" | "smoke:mailpit",
    "target_paths": ["roles/pazny.gitea/defaults/main.yml"],   # sorted, repo-relative
    "intent_class": "version-pin-bump",
    "gate_set":     "repo",
}))
```

**Deliberately excluded: the diff text, the prose rationale, the model name, the
timestamp.** If the diff were in this hash, a proposer would retry forever by
perturbing whitespace — the retry loop would optimise against the deduplicator,
which is the §2 failure mode one level down.

**`content_fp`** — "byte-identical patch re-offered":

```
content_fp = sha256(normalized_unified_diff)      # no hunk offsets, no timestamps,
                                                  # no trailing whitespace, LF-only
```

A `content_fp` collision is refused at attempt 1 — it is a no-op retry with no new
information. A `fingerprint` collision is refused after `max_attempts` (default
**2**), because a second, differently-shaped attempt at the same weakness in the
same place is legitimate; a third is thrashing.

`intent_class` is a closed enum, refused if unknown:
`version-pin-bump | config-fix | render-fix | wiring-fix | gate-add | dependency-bump`.

**The block lifts** — this matters, or the ledger becomes a permanent scar — when
any of:

- the weakness's own evidence hash changes (e.g. the `remediation-queue.json`
  item's `fix_version` moves), recorded as `weakness_evidence_sha` on the proposal;
- an operator runs `nos-loop forget <fingerprint>` (operator identity only);
- the gate set changes, which changes the fingerprint by construction.

---

## 5. THE BUDGET

`GET /api/v1/loop/budget?gate_set=repo` returns the budget as **data**, and
`POST /api/v1/loop/proposals` refuses violations with **409** naming the offending
path and the judge that claims it. Enforced by the engine, never by instruction.

> ### DECISION 5 — Deny beats allow, always. An unclassified path is denied.

Same default-closed posture as `traefik_auth_modes.get(s.id, 'proxy')`.

### 5.1 Computed from the gate set — §5's core rule

For each judge in the set, its **oracle paths** are forbidden:

| judge | forbidden because it is the oracle |
|---|---|
| pytest-anatomy | `tests/anatomy/**`, `conftest.py`, `pytest.ini` |
| ansible-lint | `.ansible-lint`, `.yamllint` |
| genome-codegen | `tools/genome-codegen.py`, its generated targets (`files/anatomy/module_utils/nos_entity.py`, `files/anatomy/face/src/lib/contracts/entity.gen.ts`), and the genome source it reads |
| nos-smoke | `tools/nos-smoke.py`, the smoke catalog |
| corpus-diff | `files/anatomy/scripts/cortex-corpus-diff.py` |

### 5.2 Always forbidden, every set

- **The engine's own source:** `files/anatomy/bone/**`, `state/judge-sets.yml`,
  `roles/pazny.bone/**`. *A loop that rewrites its own instructions is not
  improving, it is drifting.*
- `docs/**` — including this file.
- `.claude/**`, `.github/workflows/**`.
- **`state/manifest.yml`** — an added `domain_var` + `port_var` auto-derives a
  Traefik router (constraint E, REM-144). The loop may not create edge surface.
- `roles/pazny.traefik/vars/main.yml` — the skip list and auth modes.
- **Secrets:** `default.credentials.yml`, `credentials.yml`, `~/.nos/secrets.yml`,
  and anything outside the repo root.

### 5.3 Allowed roots (still subject to every deny above)

`roles/`, `files/anatomy/plugins/`, `tasks/`, `default.config.yml`, `apps/`,
`upgrades/`.

### 5.4 Size

`max_files: 5`, `max_diff_lines: 200`, **one proposal per cycle**. Two changes
under one verdict teaches nothing about either.

### 5.5 The `gate-add` carve-out

Forbidding `tests/anatomy/**` means the loop can never add a gate — and adding
gates is among the most valuable things it could do. But a proposal that adds a
gate cannot be validated by running the gate it adds: a new test that passes
proves nothing, and constraint C requires the defect be reintroduced and observed
going red, which is an *act*, not an exit code.

> ### DECISION 5a — `intent_class: gate-add` proposals are permitted to write
> `tests/anatomy/**`, are **never auto-accepted**, and are flagged
> `requires_operator: true`. The verdict for them records the retro-verification
> transcript as evidence, or it is INDETERMINATE.

This is the honest boundary of automation in this design.

---

## 6. THE INTERFACE SHAPE

> ### DECISION 6 — HTTP is the only implementation. The CLI is a thin client over
> it. No shared library, ever.

Three runtimes exist (Claude Code, Hermes, AgentKit/PHP) and a fourth is planned
(the Rust brain). A library is ported four times and drifts four ways.

### 6.1 HTTP — `127.0.0.1:8099`, loopback only (constraint E)

| method + path | scope | returns |
|---|---|---|
| `GET /api/v1/loop/weaknesses` | `loop:read` | ranked findings, each with stable `weakness_id` + `evidence_sha` |
| `GET /api/v1/loop/budget?gate_set=` | `loop:read` | allowed roots, forbidden paths, size caps |
| `POST /api/v1/loop/proposals` | `loop:propose` | `201` + uuid/fingerprint · `409` budget or fingerprint refusal |
| `POST /api/v1/loop/judge` | **`loop:judge`** | `202` + `run_id` (async — pytest is 190 s) |
| `GET /api/v1/loop/judge/{run_id}` | `loop:read` | `running` \| verdict + per-judge evidence |
| `GET /api/v1/loop/history?fingerprint=` | `loop:read` | prior attempts and their verdicts |
| `POST /api/v1/loop/forget` | **`loop:forget`** | `200` cut record · `404` nothing to forget — **operator identity only** (§4 "the block lifts", §6.2) |
| `GET /api/v1/loop/proposals?limit=` | `loop:read` | ledger list, newest first — `diff_text` excluded at the SQL column list (the run screen's read surface, 2026-08-06) |
| `GET /api/v1/loop/judge_runs?limit=&gate_set=` | `loop:read` | ledger list — outcome, `work_count` vs `min_work`, `reason` |
| `GET /api/v1/loop/verdicts?limit=` | `loop:read` | ledger list, incl. `evidence` (the run-uuid JSON that ties a baseline verdict to its judge runs) |
| `POST /api/v1/loop/verdicts` | — | **does not exist** (§3.1). The GET list above READS sealed rows; §3.1's guarantee — no endpoint that ACCEPTS a verdict — is untouched by a read, and the gate now pins exactly that: no write-method route may ever exist under this name |

### 6.2 CLI — `nos-loop`

```
nos-loop weaknesses [--json] [--top N]
nos-loop budget --gate-set repo [--json]
nos-loop propose --weakness <id> --intent <class> --paths a,b --gate-set repo [--diff -]
nos-loop judge --gate-set repo [--proposal <uuid>] [--wait]
nos-loop history --fingerprint <fp>
nos-loop verdict --replay <uuid>
nos-loop forget <fingerprint>          # operator identity only
```

> ### DECISION 6a — CLI exit codes are a **fixed small enum**, never a count.
> `0` PASS · `1` FAIL · `2` INDETERMINATE · `3` refused (budget/fingerprint) ·
> `4` config error.

Explicitly *not* nos-smoke's exit-as-count, and explicitly separating
INDETERMINATE from FAIL at the shell boundary so a wrapper cannot collapse them.

**Constraint F:** the engine and CLI are Python. **No `.sh` is added anywhere**,
so `${#array[@]}` cannot appear under `roles/*/files/`. Anyone later adding a
shell wrapper there must use `${!arr[@]}` or `${arr[@]+…}` — `{#` opens a Jinja
comment and the *render* fails, which `bash -n` will not catch.

---

## 7. WHAT I AM NOT BUILDING

Stated plainly, per constraint H.

1. **Not a per-session propose/evaluate loop.** `agent_iterations` already holds
   it — grader call, rubric, isolated context, max-3 iterations, live. This
   engine is strictly *between* sessions and does not read, write or wrap that
   table.
2. **Not a scheduler.** Pulse owns cadence. The loop ships **one** Pulse job
   (`nos-loop-cycle`), and only after §8's attended runs. No cron, no timer, no
   internal tick.
3. **Not an LLM judge.** Not even advisory in v1. The parent permits an advisory
   veto-only signal; deferred, because a veto-only channel still needs a
   false-positive budget nobody has measured.
4. **Not temporal supersession in `relations`.** Real, and the parent is right
   that the loop needs it eventually. It is a KEAP-side schema change with its own
   migration and does not belong in this contract.
5. **Not auto-apply and not auto-commit.** v1 proposes and judges. Application is
   an operator act or a forge MR. Nothing merges on a green verdict.
6. **Not a new daemon, port, edge route, manifest entry, or organ.**
7. **Not logic in the plugin.** The skills call the engine and hold no rules; the
   same ceremony must run from Hermes with no Claude in the picture.

---

## 8. CONSTRAINT COMPLIANCE

| # | constraint | how this contract meets it |
|---|---|---|
| **A** | judge is code, proposer is a model, never one identity | §3.1 no verdict-accepting endpoint; §3.4 two tokens, proposer cannot trigger judgment; §3.2 `CHECK (actor='engine:judge-runner')` |
| **B** | a step may not record its own success | §3.5 run row written before the subprocess, completed by the exit reader; killed run → `crashed` → INDETERMINATE; `work_count` parsed, never supplied |
| **C** | a gate you can satisfy by editing the gate is not one | §5.1 oracle paths computed from the gate set and refused at propose time; §8.1 retro-verification is mandatory and one was performed |
| **D** | no new prefix-derived credential | §8.2 |
| **E** | loopback only, and declare it | §1 lives in Bone, already `127.0.0.1` and already in `traefik_skip_ids`; §5.2 forbids editing `state/manifest.yml` and the Traefik vars |
| **F** | no `${#array[@]}` in `roles/*/files/*.sh` | §6.2 no shell scripts added; rule restated for future authors |
| **G** | stock Jinja only in vars files; a role default does not count | §8.3 |
| **H** | reuse, do not rebuild | Bone (process, auth, subprocess, migrations, units), Wing (`wing.db`, WORM triggers, `AuditChain`), Pulse (cadence), `agent_iterations` (untouched), the five existing judges |

### 8.1 Retro-verification (constraint C)

**Performed.** `genome-codegen --check` is one of the five judges and its failure
branch had not been observed, so it was reintroduced:

```console
$ cp files/anatomy/module_utils/nos_entity.py /tmp/nos_entity.bak
$ printf '\n# retro-verify staleness probe\n' >> files/anatomy/module_utils/nos_entity.py
$ python3 tools/genome-codegen.py --check
STALE generated artifacts: files/anatomy/module_utils/nos_entity.py
run `python3 tools/genome-codegen.py` and commit
EXIT=1
$ cp /tmp/nos_entity.bak files/anatomy/module_utils/nos_entity.py
$ python3 tools/genome-codegen.py --check
genome artifacts current (2 checked)
EXIT=0
$ git status --porcelain          # clean
```

Two false-green surfaces were also confirmed directly rather than taken on trust:

```console
$ python3 tools/nos-smoke.py --include zzz-nonexistent-service --no-jsonl
smoke catalog yielded zero entries (check filters / install_* flags)
EXIT=0

$ env -u WING_API_TOKEN HOME=/tmp/emptyhome python3 -m pytest tests/anatomy/test_hub_url_audit.py -q -rs
SKIPPED [2] tests/anatomy/test_hub_url_audit.py:85: WING_API_TOKEN not discoverable — live daemon needed
2 skipped in 0.22s
EXIT=0
```

**Not yet performed — and owed before any of this is called done.** The gates
this contract *specifies* do not exist yet, so none has been seen to fail. Each
must be retro-verified at build time, with the transcript recorded:

| gate to write | reintroduce | must go red on |
|---|---|---|
| `test_loop_has_no_verdict_endpoint.py` | add a route accepting `result` | route-table scan |
| `test_loop_verdict_writer_is_singular.py` | a second `INSERT INTO loop_verdicts` outside `ledger.py` | source scan |
| `test_loop_zero_work_is_indeterminate.py` | make `work_count==0` return pass | adapter unit test |
| `test_loop_budget_forbids_its_own_gates.py` | drop `tests/anatomy/**` from the `repo` budget | budget computation |
| `test_loop_judge_argv_pins_side_effect_flags.py` | remove `--no-ledger` / `--no-jsonl` | `state/judge-sets.yml` scan |
| `test_loop_tokens_are_not_prefix_derived.py` | restore `{{ global_password_prefix }}_pw_loop` | credentials scan |

A gate that was never seen to fail is decoration.

### 8.2 Secrets (constraint D)

Two tokens: `loop_propose_token`, `loop_judge_token`. Both are **minted random**
and persisted via `main.yml`'s lazy-regenerate group, in the established form:

```yaml
loop_judge_token: "{% if '_pw_' in (loop_judge_token | default('')) or (loop_judge_token | default('') | length) < 32 %}{{ lookup('pipe', 'openssl rand -hex 32') }}{% else %}{{ loop_judge_token }}{% endif %}"
```

persisted to `~/.nos/secrets.yml` (mode 0600, dir 0700) by the existing
`secrets.yml.j2` template. **Neither is `{{ global_password_prefix }}_pw_*`.** The
runtime blast radius stays 86 and
`tests/anatomy/test_secret_blast_radius.py` must not move — noting its own kept
lesson: *measure the runtime value, not the declaration.*

### 8.3 Vars (constraint G)

New vars (`install_loop`, `loop_judge_timeout_s`, `loop_max_diff_lines`,
`loop_max_attempts`) go in **`default.config.yml`**, and the tokens in
**`default.credentials.yml`** — not in `roles/pazny.bone/defaults/main.yml`,
because a role default is not "defined before core-up" and the loader's
`{{ vars }}` eager-resolve aborts the run on a var that only resolves later.
Stock Jinja only: `default`, `length`, `trim`, comparisons — no `regex_replace`,
no `| bool`, no `b64encode`.

---

## 9. WHAT I DELIBERATELY DID NOT DECIDE

Named, so nobody mistakes silence for settlement.

1. **The weakness ranking function.** `GET /weaknesses` returns findings with
   severity and evidence; how to *order* across four incommensurable sources
   (a HIGH remediation item vs a failing pytest node vs an open hidden fee) needs
   data from real cycles. v1 groups by source and sorts by severity within it.
2. **Sandbox mechanism.** Git worktree vs APFS copy-on-write clone. Worktree is
   assumed; clone may be much faster for a 190 s judge. Measure before choosing.
3. **`max_attempts: 2` and `max_diff_lines: 200`.** Guesses. Both are config, both
   should be re-set from the first fifty cycles.
4. **Whether INDETERMINATE pages the operator.** It should not, until its
   false-positive rate is known — an INDETERMINATE storm from a down organ at
   03:00 is exactly the alert-fatigue shape A9 was tuned to avoid.
5. **Whether `wing.db` remains the ledger's home under load.** SQLite writer
   contention between Wing, Bone and the judge runner is unmeasured. The tables
   are portable; the decision is revisitable.
6. **keap-lint's possible re-admission.** If upstream adds a read-only
   `GET /agent/v1/lint` verdict path with no reconcile and no notification, it
   becomes admissible as a judge. Not today.
7. **The Rust brain's client shape.** It is an HTTP client; beyond that, nothing
   here constrains it, and nothing here should.
8. **Cross-host / fleet semantics.** Single host. A verdict's `tree_sha` is
   meaningless across machines with different working trees.
9. **What happens when a judge itself is the weakness.** `min_work` ratchets catch
   silent scope loss, but a judge that is wrong-but-consistent is invisible to
   this design, and §5.2 forbids the loop from touching it. That is intentional
   and it is a ceiling, not an oversight.

---

## 10. BUILD ORDER

Unchanged from the parent in spirit, corrected in detail.

1. **`state/judge-sets.yml` + `judges.py` + `POST /api/v1/loop/judge`.** One
   address, five judges, three-valued verdicts, `min_work` ratchets, sandbox for
   pytest. Useful standalone, and everything else depends on it.
2. **The ledger** — schema, chain, WORM triggers, no verdict endpoint. With the
   §8.1 gates written and retro-verified.
3. **`GET /api/v1/loop/weaknesses`** — a reader over sources that already exist.
   Derive counts from `items[]`, never from `summary.by_status` (measured: it
   disagrees with its own items by 7 in both directions), and never treat
   `scan-state.json`'s `status: scanned` as evidence a scan happened.
4. **`GET /budget` + `POST /proposals`** with refusals.
5. **The plugin skills**, thin over 1–4.
6. **One Pulse job**, only after enough attended cycles to trust the above.

---

## 11. WHAT WOULD PROVE IT WORKS

The parent's §7 criterion — *"a weakness that was on the list, is not on the
list"* — is right about the ESTATE and wrong about the LOOP, and adopting it
unchanged made this section unsatisfiable (fable review `docs/idea/13`, §3.1):
`budget.py`'s `Rule("docs/**", "doctrine", "§5.2")` forbids the loop from
writing under `docs/`, and most live weaknesses (the remediation queue under
`docs/llm/security/`, the hidden fees under `docs/hidden_fees/`) can only leave
the list via such a write. The cheapest way to "satisfy" the old wording was to
carve a hole in `docs/**` — the one rule standing between the loop and its own
doctrine — so the wording goes, not the wall.

The reachable criterion, which is what the loop actually contributes:

> A weakness that was on the list has a judged diff MERGED into `dev` behind a
> green pipeline, where the verdict was produced by a judge the proposer could
> not touch, the merge was performed by a reviewer that answered its three
> questions YES, and no step in between recorded its own success.

The remaining links — an operator converges, the scanner re-scans, the row
retires — belong OUTSIDE the loop by design (§7 non-goal 5, §5.2), and the loop
contributing one link of six is still a loop. Whether the weakness then left
the list is the scanner's answer, read from the queue, never asserted by
anything that took part in the merge.

With one addition this contract earns: **and the verdict replays.**
`nos-loop verdict --replay <uuid>` re-runs the recorded `argv` against the
recorded `tree_sha` and reproduces the recorded `exit_code`, `work_count` and
`stdout_sha`. A verdict that cannot be replayed is a claim, and this estate spent
v0.10-beta learning what claims are worth.
