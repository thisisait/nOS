"""Agentic-loop ledger — schema, fingerprints, and the ONLY verdict writer.

Contract: docs/idea/11-agentic-loop-contract.md §3 (the ledger), §4
(fingerprinting), §2.4 (absence is never success). This module is build-order
item 2: it mounts no routes and spawns no process of its own. `judges.py`
(build-order item 1) is the derivation site — adapters, work counts, the §2.4
ratchet, the sandbox — and this module persists what its exit reader produced.
`loop.py` (routes) lands separately and calls both.

WHY A PROPOSER STRUCTURALLY CANNOT WRITE A VERDICT
--------------------------------------------------
Constraint A: the judge is code, the proposer is a model, and they never share
an identity. That is enforced here in five layers, weakest claim last, so the
guarantee can be audited rather than believed:

  1. **No API surface accepts a result, OR SELECTS THE EVIDENCE FOR ONE.**
     `ProposerLedger` has no method that writes to `loop_verdicts`, and
     `EvaluatorLedger.seal_verdict()` takes no `result` parameter — the result
     is DERIVED from stored `loop_judge_runs` rows, which are themselves derived
     from a subprocess's raw exit code and stdout.
     (§3.1 DECISION 3: `POST /v1/verdicts` is deleted from the design.)

     "No result parameter" was necessary and NOT sufficient, and an adversarial
     review proved it end to end: seal_verdict used to take `run_uuids` and
     `expected_judges` as caller-supplied lists and validate neither against the
     registry, the proposal, or each other. With one PASS run and one FAIL run
     persisted against the SAME proposal, `run_uuids=[the pass]` +
     `expected_judges=[]` sealed `result='pass'` and `verify_chain()` said ok —
     the FAIL sat in `loop_judge_runs` while the hash-chained verdict said pass.
     A `fast` run of one proposal could also be re-attached to a different
     proposal, a different gate set and a different `tree_sha`. Selection is
     forgery: you do not need to invent a value if you can choose which facts
     the aggregator is shown. So this module now supplies its own evidence —
     `gate_set` + `proposal_uuid` in, every unsealed run row on record for that
     pair out, membership read from `judges.load_registry()`, and `tree_sha`
     read off the runs rather than typed by the caller.
  2. **The connection refuses it.** Each role opens wing.db behind an sqlite3
     authorizer with a per-role writable-table set. A proposer holding its own
     connection object — encapsulation already broken — still gets
     `sqlite3.DatabaseError: not authorized` on `INSERT INTO loop_verdicts`,
     on `DROP TRIGGER`, and on `ATTACH`.
  3. **The schema refuses it.** `CHECK (actor = 'engine:judge-runner')` rejects
     any insert naming another writer, on any connection.
  4. **The WORM triggers refuse edits.** A chained verdict row cannot be
     UPDATEd or DELETEd; a finished judge run cannot have its exit code
     rewritten.
  5. **The chain makes offline tampering evident.** Not prevented — the
     estate's own `test_audit_chain.py:188` drops a WORM trigger to simulate an
     offline attacker (M6), and on a single-UID host that is possible here too.
     `verify_chain()` reports BROKEN, mirroring `verify-audit-chain.php`.

  NOT CLAIMED: filesystem separation between proposer and judge. §3.3 is
  explicit about this, and the real guarantee is replay — every verdict stores
  `tree_sha`, `argv`, `exit_code`, `work_count` and `stdout_sha`.

CONSTRAINT B — no step records its own success
----------------------------------------------
`begin_judge_run()` writes `status='running'` BEFORE the subprocess starts.
`finish_judge_run()` persists the record built by `judges._spawn_and_read` —
the code that READ the exit — and refuses (rather than shrugging) when the row
it meant to complete is no longer 'running'. A killed run stays 'running' until
`sweep_crashed()` marks it 'crashed', which aggregates to INDETERMINATE, never
PASS. And `loop_judge_runs` carries a CHECK that refuses to STORE a PASS whose
work count is missing or below its ratchet: §2.4 as a storage constraint, so a
future runner that forgets the rule cannot record a green anyway.

CONSTRAINT D — no new credential. This module mints nothing and reads no
password prefix. The chain key reuses the EXISTING `WING_EVENTS_HMAC_SECRET`
when present and falls back to plain sha256 (the shape §3.2 specifies), so the
runtime blast radius does not move.

CONSTRAINT H — reuse. wing.db is opened through `clients/wing.py`, the single
seam pinned by `tests/callback/test_bone_insert_event.py`. The hash-chain
discipline is `App\\Model\\AuditChain`'s. `agent_iterations` is NOT touched:
that table owns the per-SESSION loop; this ledger is strictly BETWEEN sessions.

SCHEMA HOME: the DDL below is the single declaration site for `loop_*`. It is
deliberately NOT duplicated into `files/anatomy/wing/db/schema-extensions.sql`
— a twin would drift, and Bone is the only writer. Pinned by
`test_loop_ledger.py::test_loop_schema_is_declared_in_exactly_one_place`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import uuid as _uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import budget  # §5 — the path budget, computed from the gate set
import judges  # THE derivation site: adapters, work counts, aggregation (§2.2)
from clients import wing as _wing  # single wing.db seam (constraint H)

# ── Vocabulary ────────────────────────────────────────────────────────────

#: The only value `loop_verdicts.actor` may hold. Enforced by a CHECK, not prose.
ENGINE_ACTOR = "engine:judge-runner"

#: §4 — closed enum; an unknown intent_class is refused at propose time.
INTENT_CLASSES = frozenset({
    "version-pin-bump", "config-fix", "render-fix",
    "wiring-fix", "gate-add", "dependency-bump",
})

#: §5a — `gate-add` writes the oracle's own directory, so it is never
#: auto-accepted. Set by the ledger from intent_class; NOT caller-supplied.
OPERATOR_REQUIRED_INTENTS = frozenset({"gate-add"})

#: Three-valued, deliberately. `judges.Result` is the enum; this is the SQL
#: vocabulary the CHECK constraints pin, kept as data so a test can read it.
RESULTS = ("pass", "fail", "indeterminate")

#: §4 — default retry ceiling on one (weakness, paths, intent, gate_set).
DEFAULT_MAX_ATTEMPTS = 2

#: Per-role writable tables. Everything else is denied by the authorizer.
_ROLE_WRITES: dict[str, frozenset[str]] = {
    "proposer": frozenset({"loop_proposals"}),
    "evaluator": frozenset({"loop_judge_runs", "loop_verdicts"}),
    "operator": frozenset({"loop_forgets"}),
    "reader": frozenset(),
}

_CHAIN_LABEL = b"nos-loop-verdicts-chain-v1"
_GENESIS = "nos-loop-ledger-genesis-v1"
_VERDICT_CANON_FIELDS = (
    "uuid", "proposal_id", "gate_set", "result", "actor",
    "tree_sha", "evidence", "created_at",
)

_STDOUT_HEAD_MAX = 2000

# HEAD ALONE THREW AWAY THE ANSWER. A `repo` gate set sealed FAIL on
# 2026-08-03 with eighteen pytest failures, and the stored excerpt was 2000
# characters of progress dots — pytest, like most runners, puts its summary and
# the names of what failed at the END. The one field an operator would read to
# learn WHICH test failed held the least informative part of the output.
#
# So: head for the start-of-run context (which interpreter, which warnings) and
# TAIL for the verdict's actual reasons. Split rather than doubled, so the row
# does not grow.
_STDOUT_TAIL_MAX = 2000


def _stdout_excerpt(text: str) -> str:
    """Both ends of a judge's output, with the middle named rather than dropped."""
    if len(text) <= _STDOUT_HEAD_MAX + _STDOUT_TAIL_MAX:
        return text
    dropped = len(text) - _STDOUT_HEAD_MAX - _STDOUT_TAIL_MAX
    return (text[:_STDOUT_HEAD_MAX]
            + f"\n\n[... {dropped} characters elided ...]\n\n"
            + text[-_STDOUT_TAIL_MAX:])


# ── Errors ────────────────────────────────────────────────────────────────

class LedgerError(Exception):
    """Base class; carries the HTTP status `loop.py` should surface."""

    status = 500


class ProposalRefused(LedgerError):
    """Budget/fingerprint refusal — §5/§4. Surfaces as 409.

    `reason` is a stable machine code, never free text:
      missing-diff        — no diff_text: a proposal IS its artifact, and
                            without one neither the budget nor the dedup can
                            look at what would actually change
      content-fp-repeat   — byte-identical patch already offered, under ANY
                            fingerprint (an operator forget lifts it)
      already-failed      — attempts exhausted and the last verdict was fail
      passed-awaiting-act — a prior attempt at this fingerprint already holds
                            a latest verdict of `pass`; the weakness waits on
                            an act OUTSIDE the loop (merge → converge →
                            rescan — docs/idea/11-agentic-loop-contract.md
                            §11), not on another proposal. Lifted the
                            same two ways as the ceiling: the weakness's
                            evidence changes, or an operator forget
      fingerprint-exhausted — attempts exhausted (last verdict indeterminate)
      attempt-pending     — a prior attempt has no verdict yet
      unknown-intent      — intent_class outside the closed enum
      unknown-weakness    — §4: weakness_id is not reported by any source from
                            COMMITTED content, so there is no evidence hash to
                            key the ceiling on
      bad-path            — absolute path or `..` escape in target_paths
      budget-violation    — §5: a target path the gate set forbids, including
                            the oracle of a judge that will grade it, a path the
                            DIFF touches but the proposal did not declare, a
                            declared path the diff never touches, a gate-add
                            whose diff modifies (rather than creates) a file
                            under tests/anatomy/, or any of those spelled in a
                            different case
      unknown-gate-set    — §5: no budget can be computed, so nothing is allowed
    """

    status = 409

    def __init__(self, reason: str, detail: str = "", *, prior: Sequence[Any] = ()):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.prior = list(prior)


class NotAuthorised(LedgerError):
    status = 403


class NothingToForget(LedgerError):
    """`forget` named a fingerprint no proposal carries — 404.

    A forget that 'succeeds' by cutting nothing is a success marker written
    over a typo: the operator walks away believing the wedge is lifted while
    the real fingerprint stays blocked. Refusing is the honest answer, and it
    is also what keeps `loop_forgets` an audit trail of lifts that HAPPENED
    rather than lifts that were attempted."""

    status = 404


# ── Schema ────────────────────────────────────────────────────────────────

# NOTE vs contract §3.2: two columns are added that §4/§5a require but the
# section's SQL block omits — `loop_proposals.weakness_evidence_sha` (the block
# lifts when the weakness's evidence changes) and `loop_proposals.
# requires_operator` (§5a gate-add). `loop_judge_runs.outcome` is added so
# seal_verdict aggregates from PERSISTED rows rather than in-memory state,
# which is what makes a verdict replayable.
_DDL = """
CREATE TABLE IF NOT EXISTS loop_proposals (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                  TEXT NOT NULL UNIQUE,
    fingerprint           TEXT NOT NULL,
    content_fp            TEXT,
    weakness_id           TEXT NOT NULL,
    weakness_evidence_sha TEXT,
    intent_class          TEXT NOT NULL CHECK (intent_class IN (
                              'version-pin-bump','config-fix','render-fix',
                              'wiring-fix','gate-add','dependency-bump')),
    gate_set              TEXT NOT NULL,
    target_paths          TEXT NOT NULL,
    tree_sha              TEXT NOT NULL,
    proposer_id           TEXT NOT NULL,
    proposer_model        TEXT,
    attempt_n             INTEGER NOT NULL DEFAULT 1,
    requires_operator     INTEGER NOT NULL DEFAULT 0,
    -- The artifact itself (A1/A2). content_fp is a hash of this, and a hash
    -- whose preimage is discarded cannot be audited, replayed, or ever judged:
    -- the sandbox that will apply a proposal needs the bytes, not the digest.
    diff_text             TEXT,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_loop_prop_fp     ON loop_proposals (fingerprint);
CREATE INDEX IF NOT EXISTS idx_loop_prop_weak   ON loop_proposals (weakness_id);
CREATE INDEX IF NOT EXISTS idx_loop_prop_cfp    ON loop_proposals (content_fp);

CREATE TABLE IF NOT EXISTS loop_judge_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid         TEXT NOT NULL UNIQUE,
    proposal_id  INTEGER,
    gate_set     TEXT NOT NULL,
    judge_name   TEXT NOT NULL,
    argv         TEXT NOT NULL,
    sandbox_path TEXT,
    status       TEXT NOT NULL CHECK (status IN ('running','exited','crashed','skipped')),
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    exit_code    INTEGER,
    work_count   INTEGER,
    min_work     INTEGER,
    outcome      TEXT CHECK (outcome IN ('pass','fail','indeterminate')),
    -- The tree THIS judge observed, read out of its sandbox by
    -- `judges.git_worktree_sandbox` — or, for an attached run, the
    -- `git write-tree` id of base + the proposal's stored diff (A1). The
    -- verdict's tree_sha is derived from these; it is not a caller's label.
    tree_sha     TEXT,
    -- The ENGINE-chosen base the diff was applied to: the repo's HEAD at run
    -- time, never the proposer's declared tree_sha. Equal to tree_sha on
    -- baseline runs. Without it a replay cannot reconstruct the judged tree
    -- from the stored diff.
    base_sha     TEXT,
    stdout_sha   TEXT,
    stdout_head  TEXT,
    -- WHY a judge reached its outcome, and the only field that makes a SKIP
    -- actionable. It was computed by `judges._executable_present`, carried on
    -- the in-memory JudgeRun, and dropped here: the first real turn of the loop
    -- (2026-08-03) sealed `reason: "ansible-lint: "` — it knew WHICH judge had
    -- not run and could not say that the binary was missing from the daemon's
    -- PATH. A record that loses the actionable half is the defect this ledger
    -- exists to catch, one level in.
    reason       TEXT,
    -- WHAT actually ran (A4): argv[0] as resolved under the judge env, and
    -- that binary's `--version` line, both measured by the engine. The
    -- literal argv ("python3") named the dev pyenv AND Bone's pytest-less
    -- venv with one identity, so a §11 replay could not tell "same result"
    -- from "same mistake". Persisted for the same reason `reason` is: a
    -- field computed in judges.py and dropped at this boundary is how the
    -- skip reason was lost the first time.
    resolved_argv0 TEXT,
    interpreter    TEXT,
    -- §2.4 DECISION 2b, as a STORAGE constraint: a PASS that cannot show its
    -- work is not storable. Closes M2 (nos-smoke "zero entries", exit 0) and
    -- M3 (pytest "2 skipped", exit 0) at a layer no runner can forget.
    CHECK (outcome IS NULL OR outcome <> 'pass' OR (
              status = 'exited' AND work_count IS NOT NULL
              AND min_work IS NOT NULL AND work_count >= min_work))
);
CREATE INDEX IF NOT EXISTS idx_loop_runs_prop ON loop_judge_runs (proposal_id);


CREATE TABLE IF NOT EXISTS loop_verdicts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid         TEXT NOT NULL UNIQUE,
    proposal_id  INTEGER,
    gate_set     TEXT NOT NULL,
    result       TEXT NOT NULL CHECK (result IN ('pass','fail','indeterminate')),
    actor        TEXT NOT NULL CHECK (actor = 'engine:judge-runner'),
    tree_sha     TEXT NOT NULL,
    evidence     TEXT NOT NULL,
    prev_hash    TEXT,
    row_hash     TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
-- ONE LINK PER PREDECESSOR. seal_verdict reads the tip's row_hash and then
-- INSERTs; two concurrent seals read the SAME tip and both write, forking the
-- chain. verify_chain() then reports ok:false forever, because the WORM
-- triggers refuse DELETE and UPDATE to every role — an ordinary scheduling
-- race would permanently destroy the tamper-evidence, with no repair path in
-- any code path that exists. This index makes the second writer FAIL instead,
-- which is recoverable: it retries and chains onto the new tip.
CREATE UNIQUE INDEX IF NOT EXISTS idx_loop_verdicts_prev
    ON loop_verdicts (prev_hash) WHERE prev_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_loop_verdicts_prop ON loop_verdicts (proposal_id);

-- §4 "the block lifts" — operator-only. CHECK pins the writer identity the
-- same way loop_verdicts does; the authorizer denies this table to every
-- other role.
CREATE TABLE IF NOT EXISTS loop_forgets (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint          TEXT NOT NULL,
    through_proposal_id  INTEGER NOT NULL,
    actor                TEXT NOT NULL CHECK (actor = 'operator'),
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_loop_forgets_fp ON loop_forgets (fingerprint);

-- WORM. Modelled on events_worm_update/_delete (init-db.php:401) but STRICTER:
-- CREATE ... IF NOT EXISTS, never DROP-then-CREATE. init-db.php drops first
-- because it must UPDATE a definition on a pre-existing wing.db; these tables
-- are new, so a drop would only open a window in which a concurrent connection
-- sees the table unprotected.
-- a chained verdict row has no mutable column at all, and a finished judge run
-- may not have its exit code rewritten after the fact (constraint B).
CREATE TRIGGER IF NOT EXISTS loop_verdicts_worm_update BEFORE UPDATE ON loop_verdicts
FOR EACH ROW WHEN OLD.row_hash IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'loop_verdicts WORM: verdict rows are append-only'); END;

CREATE TRIGGER IF NOT EXISTS loop_verdicts_worm_delete BEFORE DELETE ON loop_verdicts
FOR EACH ROW WHEN OLD.row_hash IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'loop_verdicts WORM: verdict rows are append-only'); END;

CREATE TRIGGER IF NOT EXISTS loop_judge_runs_worm_update BEFORE UPDATE ON loop_judge_runs
FOR EACH ROW WHEN OLD.status <> 'running'
BEGIN SELECT RAISE(ABORT, 'loop_judge_runs WORM: a finished run is immutable'); END;

CREATE TRIGGER IF NOT EXISTS loop_judge_runs_worm_delete BEFORE DELETE ON loop_judge_runs
FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'loop_judge_runs WORM: evidence is append-only'); END;
"""


#: Columns added after the first cut of `_DDL`. `CREATE TABLE IF NOT EXISTS`
#: is a no-op on a database that already has the table, so a column added later
#: needs its own idempotent sweep — the same discipline as the Wing `/events`
#: schema (P1). Kept as data so the gate can read it.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("loop_judge_runs", "tree_sha", "TEXT"),
    ("loop_judge_runs", "reason", "TEXT"),
    ("loop_judge_runs", "resolved_argv0", "TEXT"),
    ("loop_judge_runs", "interpreter", "TEXT"),
    ("loop_judge_runs", "base_sha", "TEXT"),
    ("loop_proposals", "diff_text", "TEXT"),
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Idempotent DDL. Runs on a bootstrap connection BEFORE the authorizer is
    installed — every role connection denies CREATE/DROP/ALTER afterwards."""
    conn.executescript(_DDL)
    for table, column, decl in _ADDED_COLUMNS:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.commit()


# ── Fingerprints (§4) ─────────────────────────────────────────────────────

def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalize_paths(paths: Iterable[str]) -> list[str]:
    """Repo-relative, de-duplicated, sorted. Refuses escapes.

    Not the budget (§5, budget.py) — just the canonical form the fingerprint
    hashes, so `["b","a"]` and `["a","b","a"]` are the same attempt.
    """
    out: set[str] = set()
    for raw in paths:
        p = str(raw).strip().replace("\\", "/")
        while p.startswith("./"):
            p = p[2:]
        if not p:
            continue
        if p.startswith("/") or p.startswith("~"):
            raise ProposalRefused("bad-path", f"not repo-relative: {raw}")
        if ".." in p.split("/"):
            raise ProposalRefused("bad-path", f"escapes the repo root: {raw}")
        out.add(p)
    if not out:
        raise ProposalRefused("bad-path", "no target paths")
    return sorted(out)


def fingerprint(weakness_id: str, target_paths: Iterable[str],
                intent_class: str, gate_set: str) -> str:
    """"The same attempt at the same thing."

    §4, verbatim on the exclusions: the diff text, the prose rationale, the
    model name and the timestamp are DELIBERATELY out. If the diff were in this
    hash a proposer would retry forever by perturbing whitespace — the retry
    loop would optimise against the deduplicator, which is §2's failure mode
    one level down.
    """
    if intent_class not in INTENT_CLASSES:
        # NAME the enum. The propose skill promises the refusal does; it used
        # to echo back only the rejected guess, so nine wrong guesses taught a
        # proposer nothing nine times (2026-08-27, REM-229 on MiniMax).
        raise ProposalRefused(
            "unknown-intent",
            f"{intent_class!r} is not one of: {', '.join(sorted(INTENT_CLASSES))}",
        )
    payload = {
        "weakness_id": str(weakness_id),
        "target_paths": normalize_paths(target_paths),
        "intent_class": intent_class,
        "gate_set": str(gate_set),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


_HUNK_RE = re.compile(r"^@@[^@]*@@")
_INDEX_RE = re.compile(r"^index [0-9a-f]+\.\.[0-9a-f]+")


def normalize_diff(diff_text: str) -> str:
    """Strip what is incidental to a patch's content: hunk offsets, blob
    indices, ---/+++ header timestamps, CRLF, trailing whitespace."""
    lines: list[str] = []
    for raw in diff_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        if _INDEX_RE.match(line):
            continue
        if line.startswith("@@"):
            line = _HUNK_RE.sub("@@", line).rstrip()
        elif line.startswith("--- ") or line.startswith("+++ "):
            line = line.split("\t")[0].rstrip()
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def content_fingerprint(diff_text: str) -> str:
    """"The byte-identical patch, re-offered." Refused at any attempt: a no-op
    retry carries no new information."""
    return hashlib.sha256(normalize_diff(diff_text).encode("utf-8")).hexdigest()


# ── Where derivation lives, and why not here (constraint H) ───────────────
#
# An earlier draft of this module carried its own JudgeSpec, its own adapter
# table and its own work-count parser. That was a SECOND implementation of the
# one rule the loop cannot afford to have two of — "what does this exit code
# mean" — and the two would have drifted on their first disagreement. Worse,
# the copy was already wrong: it read work counts from stdout, and ansible-lint
# writes its work line to STDERR, so every green ansible-lint run would have
# been recorded INDETERMINATE.
#
# `judges.py` owns derivation: `ADAPTERS` construct the Result, `work_count()`
# reads the subprocess's own output, and `_spawn_and_read` applies the §2.4
# ratchet to a PASS. The ledger PERSISTS what the exit reader produced and
# re-derives nothing.
#
# What the ledger does add is an INDEPENDENT check, in the schema rather than
# in code: `loop_judge_runs` has a CHECK that refuses to STORE a PASS whose
# work count is missing or below its ratchet. That is not a duplicate of the
# adapter (it knows nothing about exit codes); it is the one invariant of §2.4
# expressed where no code path can bypass it — including a future runner that
# forgets to apply it.


# ── Chain (§3.2) ──────────────────────────────────────────────────────────

def _chain_key() -> str | None:
    """Reuses the EXISTING events HMAC secret under a distinct label. Mints
    nothing (constraint D)."""
    s = os.getenv("WING_EVENTS_HMAC_SECRET", "")
    if not s:
        return None
    return hmac.new(s.encode(), _CHAIN_LABEL, hashlib.sha256).hexdigest()


def _verdict_canonical(values: dict[str, Any]) -> str:
    ordered = {f: values.get(f) for f in _VERDICT_CANON_FIELDS}
    return json.dumps(ordered, separators=(",", ":"), ensure_ascii=False)


def chain_hash(prev: str, values: dict[str, Any]) -> str:
    """sha256(prev ‖ canonical_row) — HMAC-keyed when a secret exists.

    Unlike `events`, the loop chain is ALWAYS on: these tables are new, so
    there are no legacy unchained rows for the WORM triggers to be dormant
    over, and a verdict is the one row in the estate whose value is the reward
    signal for the next modification.
    """
    key = _chain_key()
    msg = (prev + _verdict_canonical(values)).encode("utf-8")
    if key:
        return hmac.new(key.encode(), msg, hashlib.sha256).hexdigest()
    return hashlib.sha256(msg).hexdigest()


# ── Connections ───────────────────────────────────────────────────────────

_WRITE_ACTIONS = (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE)
_SCHEMA_ACTIONS = (
    sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_DROP_TRIGGER,
    sqlite3.SQLITE_DROP_INDEX, sqlite3.SQLITE_ALTER_TABLE,
    sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_CREATE_INDEX,
)


def _authorizer_for(role: str):
    writable = _ROLE_WRITES[role]

    def _auth(action: int, arg1: Any, arg2: Any, dbname: Any, source: Any) -> int:
        # DROP TRIGGER is exactly the M6 bypass (test_audit_chain.py:188 does it
        # to simulate an offline attacker). It is denied on every role
        # connection — an attacker must go around this module, not through it.
        if action in _SCHEMA_ACTIONS:
            return sqlite3.SQLITE_DENY
        # ATTACH would re-open the same file under a name whose table checks
        # this callback never sees.
        if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
            return sqlite3.SQLITE_DENY
        if action in _WRITE_ACTIONS:
            table = arg1 or ""
            if table not in writable:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return _auth


def _connect(role: str) -> sqlite3.Connection:
    if role not in _ROLE_WRITES:
        raise LedgerError(f"unknown ledger role: {role}")
    conn = _wing.open_connection()        # single seam (constraint H)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)                   # before the authorizer: DDL is denied after
    conn.set_authorizer(_authorizer_for(role))
    return conn


def default_weakness_index() -> dict[str, str]:
    """`{weakness_id: evidence_sha}`, from the reader that DERIVES both.

    §4 lifts a fingerprint block when "the weakness's own evidence hash
    changes". That hash has exactly one authoritative derivation —
    `weaknesses.Weakness.evidence_sha` — and until now the ledger never
    consulted it: `weakness_evidence_sha` arrived as a proposer-supplied string
    and `weakness_id` was hashed verbatim. MEASURED: four proposals identical in
    every substantive field, each sealed FAIL, each carrying a fresh nonce
    ('sha-0'…'sha-3') — all four ACCEPTED, against a control that refuses the
    third. Varying `weakness_id` alone did the same. The retry ceiling is the
    only defence against grinding a non-deterministic judge (`nos-smoke` and
    `cortex-corpus-diff` are declared `deterministic: false`) until it comes
    back green, and it was keyed on two fields the grinder writes.

    Imported lazily so importing the ledger does not drag in the reader's
    FastAPI router; the reader is READ-ONLY and holds no opinion (its own
    docstring), which is why it is safe for the ledger to depend on it.

    COMMITTED CONTENT ONLY. The reader reads its file ledgers straight off the
    working tree — deliberately, its job is to see what is there — but §4 keys
    the retry ceiling on `(weakness_id, evidence_sha)`, and both of those are
    derived from file CONTENT. MEASURED: one uncommitted row appended to
    docs/hidden_fees/README.md minted a brand-new `fee:` weakness_id that this
    index served to the ceiling check, so a proposer with filesystem access
    could invent lift keys without a commit, a review, or a trace in history.
    A weakness whose evidence derives from uncommitted content is therefore
    NOT proposable: `Weakness.evidence_committed` is computed by the source
    that read the file (it knows every path it touched, including the per-fee
    body files the index table links to), and this index drops the rest. The
    weakness still APPEARS in `/weaknesses` — observing is the reader's job —
    it just cannot key a ceiling until it is committed.
    """
    import weaknesses as _weaknesses  # noqa: PLC0415 — see the docstring

    return {
        w.weakness_id: w.evidence_sha
        for report in _weaknesses.collect()
        for w in report.weaknesses
        if w.evidence_committed
    }


def default_uncommitted_weakness_ids() -> set[str]:
    """The weaknesses the index above WITHHELD, so a refusal can say why.

    MEASURED 2026-08-19: while `docs/llm/security/remediation-queue.json` sat
    uncommitted (the nightly scan writes it; nobody commits it), the index
    served 13 of 69 weaknesses — every one a `fee:`, and a `fee:` closes only
    by writing `docs/**`, which every gate set's budget forbids. For several
    hours the loop could propose against NOTHING it was also allowed to fix,
    and the refusal it gave ("not reported by any weakness source") was a lie
    of classification: the source reported it loudly; the ledger had withheld
    it, correctly, for an uncommitted-evidence reason the message never named.
    This deadlock recurs on every scan-write that nobody commits, so the
    refusal must carry its own remedy. See §11 of the contract.
    """
    import weaknesses as _weaknesses  # noqa: PLC0415 — same seam as the index

    return {
        w.weakness_id
        for report in _weaknesses.collect()
        for w in report.weaknesses
        if not w.evidence_committed
    }


def open_ledger(role: str, *, registry: Any = None,
                weakness_index: Any = None):
    """Factory. `role` picks the CLASS, and the class's method set IS the
    capability — there is no runtime `if role == …` branch guarding a shared
    verdict writer, because there is no shared verdict writer.

    `registry` and `weakness_index` are CONSTRUCTION-time dependencies with real
    defaults (the committed `state/judge-sets.yml` and the live weakness
    reader), deliberately not per-call parameters. That distinction is the whole
    point: `loop.py` builds the ledger, so nothing in a request BODY can reach
    either — which is exactly how `expected_judges` and `weakness_evidence_sha`
    used to be reachable.
    """
    cls = {
        "proposer": ProposerLedger,
        "evaluator": EvaluatorLedger,
        "operator": OperatorLedger,
        "reader": ReaderLedger,
    }[role]
    return cls(_connect(role), registry=registry, weakness_index=weakness_index)


# ── Ledgers ───────────────────────────────────────────────────────────────

def _as_judge_run(row: dict[str, Any]) -> "judges.JudgeRun":
    """A persisted row, back into the shape `judges.aggregate` reasons over.

    One aggregation rule in the estate, applied to rows that survived the
    schema's CHECKs — rather than a second rule here that could disagree with
    the first.
    """
    return judges.JudgeRun(
        judge_name=row["judge_name"],
        gate_set=row["gate_set"],
        argv=tuple(json.loads(row["argv"])),
        status=row["status"],
        result=judges.Result(row["outcome"]) if row["outcome"] else None,
        exit_code=row["exit_code"],
        work=row["work_count"],
        min_work=row["min_work"] or 0,
        stdout_sha=row["stdout_sha"],
        tree_sha=row["tree_sha"],
        base_sha=row["base_sha"] if "base_sha" in row.keys() else None,
        reason=row["reason"] if "reason" in row.keys() else "",
        resolved_argv0=row["resolved_argv0"] if "resolved_argv0" in row.keys() else None,
        interpreter=row["interpreter"] if "interpreter" in row.keys() else None,
    )


@dataclass
class Decision:
    allowed: bool
    reason: str | None
    attempt_n: int
    prior_attempts: list[dict[str, Any]] = field(default_factory=list)
    requires_operator: bool = False
    #: §5 — every budget violation, each naming the path and the judge that
    #: claims it. Populated only when `reason == 'budget-violation'`.
    violations: list[Any] = field(default_factory=list)


class ReaderLedger:
    """Read-only surface. Shared by every role — reads are not the risk."""

    def __init__(self, conn: sqlite3.Connection, *, registry: Any = None,
                 weakness_index: Any = None):
        self.__conn = conn
        self.__registry = registry
        self.__weakness_index = weakness_index
        self.__weakness_cache: dict[str, str] | None = None

    # ── derived dependencies (see `open_ledger`) ──
    def _registry(self) -> "judges.Registry":
        """The committed registry, unless one was injected at construction."""
        if self.__registry is None:
            self.__registry = judges.load_registry()
        return self.__registry

    def _weakness_evidence_sha(self, weakness_id: str) -> str:
        """§4's lift key, LOOKED UP rather than accepted.

        An unknown `weakness_id` has no sha to look up, which is what closes the
        second nonce variant: a grinder cannot mint a fresh identity by
        inventing a weakness that no source reports.
        """
        if self.__weakness_cache is None:
            src = self.__weakness_index or default_weakness_index
            self.__weakness_cache = dict(src() if callable(src) else src)
        try:
            return self.__weakness_cache[str(weakness_id)]
        except KeyError:
            # NOT in the index — but WITHHELD is a different fact from UNSEEN,
            # and conflating them cost hours on 2026-08-19 (see
            # `default_uncommitted_weakness_ids`). Ask before claiming.
            try:
                withheld = default_uncommitted_weakness_ids()
            except Exception:  # noqa: BLE001 — a broken reader must not mask the refusal
                withheld = set()
            if str(weakness_id) in withheld:
                raise ProposalRefused(
                    "uncommitted-evidence",
                    f"{weakness_id} IS reported, but the file its evidence was "
                    f"read from does not match HEAD, so it cannot key the §4 "
                    f"retry ceiling (an uncommitted edit is a lift key the "
                    f"proposer could write for itself). Commit the evidence "
                    f"file — `git status docs/llm/security/` is the usual "
                    f"culprit: the nightly scan writes it and nobody commits it",
                ) from None
            raise ProposalRefused(
                "unknown-weakness",
                f"{weakness_id} is not reported by any weakness source; §4 keys "
                f"the retry ceiling on the SOURCE's evidence hash, so a weakness "
                f"the reader has never seen has no evidence to change",
            ) from None

    # Deliberately name-mangled: a subclass cannot hand the raw connection to a
    # caller by accident. `_q` is the only read path.
    def _q(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.__conn.execute(sql, tuple(params)).fetchall()]

    def _w(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        cur = self.__conn.execute(sql, tuple(params))
        self.__conn.commit()
        return cur

    def close(self) -> None:
        self.__conn.close()

    # ── reads ──
    def proposal(self, uuid: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM loop_proposals WHERE uuid = ?", (uuid,))
        return rows[0] if rows else None

    # ── ledger lists (the run screen's read surface, 2026-08-06) ──
    # Explicit column lists, newest first. `diff_text` is EXCLUDED from the
    # proposals list by construction: the artifact's hunks are secrets-adjacent
    # (a proposal may touch credential templates) and the browser surface that
    # consumes these lists must not be one upstream `SELECT *` away from
    # carrying them. The full row stays reachable via proposal()/history() for
    # server-side callers that need the bytes.

    def list_proposals(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._q(
            "SELECT id, uuid, fingerprint, content_fp, weakness_id, "
            "weakness_evidence_sha, intent_class, gate_set, target_paths, "
            "tree_sha, proposer_id, proposer_model, attempt_n, "
            "requires_operator, created_at "
            "FROM loop_proposals ORDER BY id DESC LIMIT ?", (int(limit),))

    def list_judge_runs(self, limit: int = 200,
                        gate_set: str | None = None) -> list[dict[str, Any]]:
        sql = ("SELECT uuid, proposal_id, gate_set, judge_name, status, "
               "started_at, finished_at, exit_code, work_count, min_work, "
               "outcome, reason, tree_sha "
               "FROM loop_judge_runs")
        params: list[Any] = []
        if gate_set:
            sql += " WHERE gate_set = ?"
            params.append(gate_set)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        return self._q(sql, params)

    def list_verdicts(self, limit: int = 100) -> list[dict[str, Any]]:
        # `evidence` is included: it is the JSON that names the judge-run uuids
        # a verdict was sealed from, and without it a client cannot tie a
        # BASELINE run (proposal_id NULL) to its verdict at all.
        return self._q(
            "SELECT uuid, proposal_id, gate_set, result, actor, tree_sha, "
            "evidence, created_at "
            "FROM loop_verdicts ORDER BY id DESC LIMIT ?", (int(limit),))

    def history(self, fingerprint_: str) -> list[dict[str, Any]]:
        """§6.1 GET /loop/history — prior attempts and their verdicts."""
        out = self._q(
            "SELECT * FROM loop_proposals WHERE fingerprint = ? ORDER BY id", (fingerprint_,))
        for p in out:
            p["verdicts"] = self._q(
                "SELECT uuid, result, gate_set, tree_sha, created_at "
                "FROM loop_verdicts WHERE proposal_id = ? ORDER BY id", (p["id"],))
            p["judge_runs"] = self._q(
                "SELECT uuid, judge_name, status, exit_code, work_count, outcome "
                "FROM loop_judge_runs WHERE proposal_id = ? ORDER BY id", (p["id"],))
        return out

    def judge_run(self, run_uuid: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM loop_judge_runs WHERE uuid = ?", (run_uuid,))
        return rows[0] if rows else None

    def verdict(self, verdict_uuid: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM loop_verdicts WHERE uuid = ?", (verdict_uuid,))
        return rows[0] if rows else None

    def replay_record(self, verdict_uuid: str) -> dict[str, Any] | None:
        """§11 — everything `nos-loop verdict --replay` needs: the recorded
        tree_sha and, per judge, the exact argv + exit_code + work_count +
        stdout_sha to reproduce. A verdict that cannot be replayed is a claim."""
        v = self.verdict(verdict_uuid)
        if v is None:
            return None
        evidence = json.loads(v["evidence"])
        run_uuids = evidence.get("judge_runs", [])
        bases = evidence.get("bases", [])
        runs = [self.judge_run(u) for u in run_uuids]
        return {
            "verdict": v,
            "tree_sha": v["tree_sha"],
            # A1 — the engine base the stored diff was applied to. With the
            # proposal's diff_text this reconstructs the judged tree byte for
            # byte (`git apply --index` + `git write-tree` is deterministic).
            "base_sha": bases[0] if len(bases) == 1 else None,
            "runs": [
                {
                    "judge_name": r["judge_name"], "argv": json.loads(r["argv"]),
                    "exit_code": r["exit_code"], "work_count": r["work_count"],
                    "stdout_sha": r["stdout_sha"], "outcome": r["outcome"],
                    "tree_sha": r["tree_sha"],
                    "base_sha": r["base_sha"] if "base_sha" in r.keys() else None,
                    # A4: a replay must run the interpreter the record ran, not
                    # merely the same literal argv — see judges.JudgeRun.identity.
                    "resolved_argv0": r["resolved_argv0"] if "resolved_argv0" in r.keys() else None,
                    "interpreter": r["interpreter"] if "interpreter" in r.keys() else None,
                }
                for r in runs if r
            ],
        }

    def verify_chain(self) -> dict[str, Any]:
        """§3.3(3) — offline tampering is DETECTED, not prevented. Mirrors
        verify-audit-chain.php: ok=False + the first broken uuid.

        `keyed` IS PART OF THE ANSWER, not a detail. Without
        WING_EVENTS_HMAC_SECRET the chain is a plain sha256 of the rows, and
        anyone able to WRITE a row can recompute it — so an unkeyed `ok: True`
        means "these rows are self-consistent", never "nobody altered them".
        Returning the same shape for both would be a degraded mode wearing the
        working mode's clothes, which is the defect class this engine exists to
        remove (2026-08-03; the ninth surviving finding of the build review).
        """
        keyed = _chain_key() is not None
        prev = _GENESIS
        checked = 0
        for row in self._q("SELECT * FROM loop_verdicts ORDER BY id"):
            expect = chain_hash(prev, row)
            if row["prev_hash"] != prev or row["row_hash"] != expect:
                return {"ok": False, "keyed": keyed, "checked": checked,
                        "broken_uuid": row["uuid"]}
            prev = row["row_hash"]
            checked += 1
        return {
            "ok": True, "keyed": keyed, "checked": checked, "broken_uuid": None,
            **({} if keyed else {"caveat":
                "UNKEYED: WING_EVENTS_HMAC_SECRET is unset, so this proves "
                "internal consistency only — a writer can forge the chain"}),
        }


class ProposerLedger(ReaderLedger):
    """The model's surface.

    Every public method here is read-or-propose. There is NO method that
    writes, computes, influences or hints at a verdict — and the connection
    underneath denies `loop_verdicts` and `loop_judge_runs` outright, so the
    absence is structural rather than editorial.
    """

    def check(self, *, weakness_id: str, target_paths: Iterable[str],
              intent_class: str, gate_set: str, content_fp: str | None = None,
              diff_text: str | None = None,
              max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> Decision:
        """§4 — the "already failed, refuse WITHOUT running" path.

        Called before any judge is triggered, and it is the only thing standing
        between an unattended loop and burning 190 s of pytest on a patch the
        estate has already judged.

        Note the signature: there is no `weakness_evidence_sha`. The value that
        LIFTS the ceiling is looked up from the weakness reader, because a lift
        the blocked party can assert is not a ceiling (see
        `_weakness_evidence_sha`).
        """
        fp = fingerprint(weakness_id, target_paths, intent_class, gate_set)
        priors = self._live_priors(fp, self._weakness_evidence_sha(weakness_id))
        requires_op = intent_class in OPERATOR_REQUIRED_INTENTS

        # §5 FIRST, before any history is consulted. A proposal that edits the
        # gate set it will be judged by is refused on its shape alone — it must
        # not be able to consume an attempt, and it must not depend on what the
        # ledger happens to remember. Deny beats allow, so a gate set with no
        # computable budget denies everything rather than nothing.
        try:
            bud = budget.budget_for(gate_set)
        except judges.ConfigError:
            return Decision(False, "unknown-gate-set", len(priors) + 1,
                            priors, requires_op)
        violations = budget.check_paths(
            target_paths, intent_class=intent_class, gate_set=gate_set,
            budget=bud, diff_text=diff_text)
        if violations:
            return Decision(False, "budget-violation", len(priors) + 1,
                            priors, requires_op, violations)

        if content_fp:
            # GLOBAL, not per-fingerprint. This lookup used to be scoped to
            # `priors` — the attempts sharing THIS fingerprint — and three of
            # the fingerprint's four inputs are proposer-chosen, so re-offering
            # a byte-identical patch under a different intent_class or gate_set
            # (or, before the declared-path-untouched rule, a padded
            # target_paths) landed in a scope where the guard could not see it:
            # same bytes, fresh ceiling, forever. The same-content question has
            # no fingerprint in it, so neither does the query.
            same = self._content_fp_priors(content_fp)
            if same:
                return Decision(False, "content-fp-repeat", len(priors) + 1, same, requires_op)

        pending = [p for p in priors if not p["verdicts"]]
        if pending:
            return Decision(False, "attempt-pending", len(priors) + 1, pending, requires_op)

        # "Passed, awaiting an act outside the loop" — checked BEFORE the
        # attempt ceiling, and regardless of it. Measured 2026-08-19 (fable
        # review §3.2): `rem:REM-204` held two sealed `pass` verdicts and the
        # tree still read the old pin, and the only thing the ledger could say
        # about it was `fingerprint-exhausted` — the same word it uses for a
        # proposal that went nowhere. A weakness the loop already SOLVED must
        # not consume further attempts, and its refusal must name what it
        # waits for (merge → converge → rescan, all outside the loop —
        # docs/idea/11-agentic-loop-contract.md §11).
        # THE verdict of a proposal is its LATEST by rowid — the rule
        # `tools/loop-status.py` had to invent (`ORDER BY id DESC LIMIT 1`)
        # because nothing said; now something says.
        passed = [p for p in priors if p["verdicts"]
                  and p["verdicts"][-1]["result"] == "pass"]
        if passed:
            return Decision(False, "passed-awaiting-act", len(priors) + 1,
                            passed, requires_op)

        if len(priors) >= max_attempts:
            last = priors[-1]["verdicts"][-1]
            reason = "already-failed" if last["result"] == "fail" else "fingerprint-exhausted"
            return Decision(False, reason, len(priors) + 1, priors, requires_op)

        return Decision(True, None, len(priors) + 1, priors, requires_op)

    def _content_fp_priors(self, content_fp: str) -> list[dict[str, Any]]:
        """Every live prior offer of this normalized patch, under ANY fingerprint.

        An operator forget still lifts it: a forgotten proposal is excluded by
        the same `through_proposal_id` cut `_live_priors` applies, correlated
        per row because different fingerprints have different cuts. Deliberately
        NOT lifted by a weakness-evidence change — new evidence can justify a
        new attempt at the fingerprint, but a byte-identical patch is the same
        act whatever the world looks like now; if it deserves a re-run, that is
        the operator's call (§6.2), not the blocked party's.
        """
        return self._q(
            "SELECT p.* FROM loop_proposals p WHERE p.content_fp = ? AND p.id > ("
            "  SELECT COALESCE(MAX(f.through_proposal_id), 0) FROM loop_forgets f"
            "  WHERE f.fingerprint = p.fingerprint) ORDER BY p.id",
            (content_fp,))

    def _live_priors(self, fp: str, weakness_evidence_sha: str) -> list[dict[str, Any]]:
        """Prior attempts that still count. §4 — the block LIFTS when the
        weakness's evidence changes or an operator forgets the fingerprint,
        or the ledger becomes a permanent scar.

        `weakness_evidence_sha` reaches here from `_weakness_evidence_sha`, i.e.
        from the source that DERIVES it. It is not optional and it is not the
        caller's: an optional lift key is a lift key the blocked party can omit.
        """
        rows = self._q(
            "SELECT COALESCE(MAX(through_proposal_id), 0) AS cut "
            "FROM loop_forgets WHERE fingerprint = ?", (fp,))
        cut = rows[0]["cut"] if rows else 0
        priors = [p for p in self.history(fp) if p["id"] > cut]
        return [p for p in priors
                if (p.get("weakness_evidence_sha") or "") == weakness_evidence_sha]

    def record_proposal(self, *, weakness_id: str, target_paths: Iterable[str],
                        intent_class: str, gate_set: str, tree_sha: str,
                        proposer_id: str, diff_text: str,
                        proposer_model: str | None = None,
                        max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> dict[str, Any]:
        """201 on acceptance; raises ProposalRefused (409) otherwise.

        Note the signature: no `result`, no `verdict`, no `status`. A proposal
        is an intent, and nothing here says whether it is any good. And no
        `weakness_evidence_sha`: §4's lift key is derived, for the same reason
        `requires_operator` is (§5a) — a field the proposer supplies is a field
        the proposer optimises.

        `diff_text` is REQUIRED. It used to be Optional, which put every check
        that reads the artifact at the proposer's discretion: omit the diff and
        the §5 artifact-vs-declaration comparison, the size cap and the
        content-fingerprint dedup all silently skipped — the exact
        gate-that-cannot-fail shape this engine exists to remove. A proposal
        without its artifact is not a proposal, so it is refused, not defaulted.
        """
        if not diff_text or not diff_text.strip():
            raise ProposalRefused(
                "missing-diff",
                "a proposal IS its artifact; without diff_text the budget "
                "cannot see what would change and the content fingerprint "
                "cannot deduplicate it")
        paths = normalize_paths(target_paths)
        fp = fingerprint(weakness_id, paths, intent_class, gate_set)
        cfp = content_fingerprint(diff_text)
        weakness_evidence_sha = self._weakness_evidence_sha(weakness_id)

        decision = self.check(
            weakness_id=weakness_id, target_paths=paths, intent_class=intent_class,
            gate_set=gate_set, content_fp=cfp, diff_text=diff_text,
            max_attempts=max_attempts)
        if not decision.allowed:
            detail = f"fingerprint {fp[:12]} attempt {decision.attempt_n}"
            if decision.violations:
                # §5 — the 409 names the offending path AND the judge that
                # claims it. A refusal a proposer cannot act on produces a
                # retry, and a retry is what the fingerprint ceiling spends.
                detail = "; ".join(str(v) for v in decision.violations)
            raise ProposalRefused(
                decision.reason or "refused", detail,
                prior=[p["uuid"] for p in decision.prior_attempts])

        u = str(_uuid.uuid4())
        self._w(
            "INSERT INTO loop_proposals "
            "(uuid, fingerprint, content_fp, weakness_id, weakness_evidence_sha, "
            " intent_class, gate_set, target_paths, tree_sha, proposer_id, "
            " proposer_model, attempt_n, requires_operator, diff_text) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (u, fp, cfp, weakness_id, weakness_evidence_sha, intent_class, gate_set,
             _canonical_json(paths), tree_sha, proposer_id, proposer_model,
             decision.attempt_n,
             # §5a — derived from intent_class by the ledger, never accepted
             # from the caller: a proposer cannot mark its own gate-add
             # auto-acceptable.
             1 if intent_class in OPERATOR_REQUIRED_INTENTS else 0,
             # The artifact, verbatim (A1 needs the bytes to judge; §11 needs
             # them to replay). The hash alone is a claim with no preimage.
             diff_text))
        return {"uuid": u, "fingerprint": fp, "content_fp": cfp,
                "attempt_n": decision.attempt_n,
                "requires_operator": decision.requires_operator}


class EvaluatorLedger(ReaderLedger):
    """The judge runner's surface — the ONLY writer of `loop_verdicts`."""

    def begin_judge_run(self, *, gate_set: str, judge_name: str,
                        argv: Sequence[str], proposal_uuid: str | None = None,
                        sandbox_path: str | None = None) -> str:
        """Constraint B — written BEFORE the subprocess starts, with
        status='running'. Nothing about the outcome exists yet, because nothing
        about the outcome is known yet."""
        proposal_id = None
        if proposal_uuid is not None:
            prop = self.proposal(proposal_uuid)
            if prop is None:
                # A refused proposal has no row, so its judges cannot run.
                raise LedgerError(f"no such proposal: {proposal_uuid}")
            proposal_id = prop["id"]
        u = str(_uuid.uuid4())
        self._w(
            "INSERT INTO loop_judge_runs "
            "(uuid, proposal_id, gate_set, judge_name, argv, sandbox_path, status, started_at) "
            "VALUES (?,?,?,?,?,?, 'running', datetime('now'))",
            (u, proposal_id, gate_set, judge_name, _canonical_json(list(argv)), sandbox_path))
        return u

    def finish_judge_run(self, run_uuid: str, *, run: "judges.JudgeRun") -> dict[str, Any]:
        """Persist the record the EXIT READER produced (`judges._spawn_and_read`).

        `run` is not a claim from a caller: nothing HTTP-reachable constructs a
        JudgeRun. `POST /api/v1/loop/judge` takes a gate-set NAME, and
        `judges.run_gate_set()` builds these from the subprocess's own exit code
        and output. The ledger re-derives nothing (one derivation site) and
        instead re-checks the one §2.4 invariant in SQL, so a runner that
        someday forgets the ratchet cannot store its PASS.
        """
        outcome = run.result.value if run.result is not None else None
        status = run.status if run.status != "running" else "crashed"
        cur = self._w(
            "UPDATE loop_judge_runs SET status=?, finished_at=datetime('now'), "
            "exit_code=?, work_count=?, min_work=?, outcome=?, tree_sha=?, "
            "base_sha=?, stdout_sha=?, stdout_head=?, reason=?, "
            "resolved_argv0=?, interpreter=? "
            "WHERE uuid=? AND status='running'",
            (status, run.exit_code, run.work, run.min_work, outcome, run.tree_sha,
             run.base_sha, run.stdout_sha,
             _stdout_excerpt(run.stdout_head or ""),
             run.reason or "", run.resolved_argv0, run.interpreter, run_uuid))
        if cur.rowcount != 1:
            # The `status='running'` guard is what stops a swept ('crashed') run
            # being resurrected as a pass. But a no-op UPDATE that still RETURNED
            # an outcome would be the exact defect this ledger exists to catch:
            # a step reporting a success it did not record. Raise instead.
            raise LedgerError(
                f"judge run {run_uuid} is not 'running' — refusing to report an "
                f"outcome that was not persisted")
        return {"uuid": run_uuid, "outcome": outcome, "status": status,
                "work_count": run.work, "exit_code": run.exit_code}

    def sweep_crashed(self) -> int:
        """Constraint B, the killed-process half: a run whose reader never
        returned stays 'running' forever. At next boot it becomes 'crashed',
        which aggregates to INDETERMINATE — never PASS."""
        cur = self._w(
            "UPDATE loop_judge_runs SET status='crashed', finished_at=datetime('now'), "
            "outcome='indeterminate' WHERE status='running'")
        return cur.rowcount

    def _sealed_run_uuids(self) -> set[str]:
        """Run uuids already folded into a verdict.

        Evidence is consumed exactly once. Without this the "every run on record
        for this pair" rule below would re-seal an earlier attempt's runs; with
        it, a FAIL that has already produced a verdict is on record as a
        verdict, which `check()` reads as `already-failed`. Either way the FAIL
        cannot be made to disappear.
        """
        used: set[str] = set()
        for row in self._q("SELECT evidence FROM loop_verdicts"):
            try:
                used.update(json.loads(row["evidence"]).get("judge_runs", []))
            except (TypeError, ValueError):
                continue
        return used

    def seal_verdict(self, *, gate_set: str,
                     proposal_uuid: str | None = None) -> dict[str, Any]:
        """The single verdict writer.

        THE SIGNATURE IS THE GUARANTEE, and it is now the whole guarantee. There
        is no `result` parameter and there never will be. There is also no
        `run_uuids`, no `expected_judges` and no `tree_sha`, because an
        adversarial review showed that supplying the SELECTION is as good as
        supplying the value: a cherry-picked `run_uuids` sealed a PASS while a
        FAIL for the same proposal sat in `loop_judge_runs`, `expected_judges=[]`
        made the missing-judge guard vacuous, and an unrelated proposal's runs
        could be re-attached to any gate set and any tree.

        What this method is given: a gate set name and (optionally) a proposal.
        What it derives:

          * membership — `judges.load_registry().gate_set(gate_set).judges`, the
            committed file that is itself inside the §5.2 deny list;
          * evidence — EVERY run row on record for `(proposal_id, gate_set)`
            that no earlier verdict has consumed. A caller cannot omit one,
            because a caller does not name them;
          * the tree — read off those rows, which got it from the sandbox they
            ran in. Judges that disagree about which tree they judged cannot
            produce a PASS, and neither can judges that cannot say.

        `judges.aggregate` still computes the value, over rows that survived the
        schema's §2.4 CHECK. Absence is caught here, the last place it could
        still read as success.
        """
        expected = list(self._registry().gate_set(gate_set).judges)

        proposal_id = None
        if proposal_uuid is not None:
            prop = self.proposal(proposal_uuid)
            if prop is None:
                raise LedgerError(f"no such proposal: {proposal_uuid}")
            proposal_id = prop["id"]

        # `IS ?` rather than `= ?` so the unattached (NULL) case is a real
        # match instead of silently matching nothing.
        consumed = self._sealed_run_uuids()
        rows = [r for r in self._q(
            "SELECT * FROM loop_judge_runs WHERE gate_set = ? AND proposal_id IS ? "
            "ORDER BY id", (gate_set, proposal_id))
            if r["uuid"] not in consumed]

        verdict = judges.aggregate([_as_judge_run(r) for r in rows], gate_set)
        result = verdict.result.value

        missing = [n for n in expected
                   if n not in {r["judge_name"] for r in rows}]
        if missing and result != "fail":
            result = "indeterminate"

        # §2.5 at the ledger layer: a verdict names ONE tree or it is not a
        # verdict. A FAIL still stands — a red is a red whatever tree it is on.
        trees = sorted({r["tree_sha"] for r in rows if r["tree_sha"]})
        tree_reason = ""
        if len(trees) > 1:
            tree_reason = f"judges observed {len(trees)} different trees: {trees}"
        elif not trees and rows:
            tree_reason = "no judge recorded the tree it judged"
        if tree_reason and result != "fail":
            result = "indeterminate"
        tree_sha = trees[0] if len(trees) == 1 else ""

        # A1's lineage half: the ENGINE-chosen base each judge's tree was built
        # from. tree_sha alone names WHAT was judged; base + the proposal's
        # stored diff is HOW to rebuild it, which is what §11 replay needs.
        bases = sorted({r["base_sha"] for r in rows
                        if "base_sha" in r.keys() and r["base_sha"]})

        prev_row = self._q(
            "SELECT row_hash FROM loop_verdicts WHERE row_hash IS NOT NULL "
            "ORDER BY id DESC LIMIT 1")
        prev = prev_row[0]["row_hash"] if prev_row else _GENESIS

        values = {
            "uuid": str(_uuid.uuid4()),
            "proposal_id": proposal_id,
            "gate_set": gate_set,
            "result": result,
            "actor": ENGINE_ACTOR,
            "tree_sha": tree_sha,
            "evidence": _canonical_json({
                "judge_runs": [r["uuid"] for r in rows],
                "expected_judges": expected,
                "missing_judges": missing,
                "outcomes": {r["judge_name"]: r["outcome"] for r in rows},
                "trees": trees,
                "bases": bases,
                "tree_note": tree_reason,
                "reason": verdict.reason,
            }),
            # Materialized, not defaulted: the chain hashes exactly what is stored.
            "created_at": self._q("SELECT datetime('now') AS t")[0]["t"],
        }
        values["prev_hash"] = prev
        values["row_hash"] = chain_hash(prev, values)

        # The unique index above is the guarantee; this is the manners. Without
        # it two seals routinely collide and one dies on a constraint error the
        # caller must interpret — with it, the loser waits for the writer lock
        # and reads the new tip on retry.
        self._w(
            "INSERT INTO loop_verdicts "
            "(uuid, proposal_id, gate_set, result, actor, tree_sha, evidence, "
            " prev_hash, row_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (values["uuid"], values["proposal_id"], values["gate_set"], values["result"],
             values["actor"], values["tree_sha"], values["evidence"],
             values["prev_hash"], values["row_hash"], values["created_at"]))
        return values


class OperatorLedger(ReaderLedger):
    """Operator identity only (§4, §6.2 `nos-loop forget`)."""

    def forget(self, fingerprint_: str) -> dict[str, Any]:
        """Lift the block on a fingerprint. Records the cut-off by proposal id
        rather than timestamp so two attempts in the same second cannot make
        the lift ambiguous.

        Raises `NothingToForget` (404) when no proposal carries the
        fingerprint: a cut at 0 excludes nothing, so recording it would be
        reporting a success that did no work."""
        rows = self._q(
            "SELECT COALESCE(MAX(id), 0) AS mx FROM loop_proposals WHERE fingerprint = ?",
            (fingerprint_,))
        through = rows[0]["mx"] if rows else 0
        if not through:
            raise NothingToForget(
                f"no proposal carries fingerprint {fingerprint_[:12]}… — "
                "nothing is blocked, so there is nothing to lift")
        self._w(
            "INSERT INTO loop_forgets (fingerprint, through_proposal_id, actor) "
            "VALUES (?,?, 'operator')", (fingerprint_, through))
        return {"fingerprint": fingerprint_, "through_proposal_id": through}
