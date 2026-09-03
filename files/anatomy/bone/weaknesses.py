"""Bone weakness reader — `GET /api/v1/loop/weaknesses`.

Build step 3 of docs/idea/11-agentic-loop-contract.md. It READS sources that
already exist and returns ranked `(severity, title, evidence, source)`. It does
not recompute, it does not judge, and it holds no opinion about what to do next.

────────────────────────────────────────────────────────────────────────────────
THE TWO REQUIREMENTS WITH TEETH
────────────────────────────────────────────────────────────────────────────────

1. THE GIT WORKING TREE IS A FIRST-CLASS SOURCE.

   The nightly security scan writes `remediation-queue.json` and
   `scan-state.json` into the repo. Nothing commits them, and nothing tells the
   operator they are sitting there — so CI, a converge, and every reader that
   goes through HEAD see a queue that is days behind the one on disk. That is
   not a lint finding about a dirty tree; it is a *scheduled job whose output
   never reached the place its consumers read from*. `_source_git_worktree`
   ranks those paths above ordinary operator edits and names the writer.

   It also annotates every other file-backed source with `file_git_state`, so a
   weakness derived from an uncommitted queue can never be mistaken for one
   derived from the committed queue.

2. SELF-REPORTED FRESHNESS IS MARKED AS SUCH.

   `scan-state.json`'s `last_full_scan` is written by the scan it describes, and
   the drift watcher trusted it for staleness — the alarm was fed the value that
   silences it. Every source therefore declares a `Freshness` with an explicit
   `basis`:

       observed         the reader measured it (git; cannot be self-reported)
       filesystem_mtime the OS stamped it (independent of the writer's claim)
       self_reported    a field INSIDE the file, written by the process the
                        field describes  ->  `self_reported: true`
       none             no freshness signal exists at all

   A weakness whose SEVERITY is derived from a self-reported value additionally
   carries `derived_from_self_report: true`, and its `observed` block carries
   the independent corroborator (`~/.nos/events/scan.jsonl` is append-only and
   written per batch, so it is not the scanner's opinion of itself). When the
   claim and the corroborator disagree, that disagreement is emitted as its own
   weakness — the reader never resolves it silently in either direction.

────────────────────────────────────────────────────────────────────────────────
ABSENCE IS NEVER SUCCESS (constraint B, and the reader's own §2.4)
────────────────────────────────────────────────────────────────────────────────

The measured defect in this estate's own judges is that doing no work exits 0:
`nos-smoke --include zzz-nonexistent` reports "zero entries" and exits 0;
pytest with no discoverable token reports "2 skipped" and exits 0. A reader that
silently returned `[]` when a source failed to load would ship that same defect
into the thing built to detect it.

So: a source NEVER contributes silence. It contributes a `SourceReport` with an
explicit status, and a failure to read becomes a weakness of its own. `complete`
is true only when every source reported `ok`. An empty `weaknesses` list means
"nothing found"; `complete: false` means "and you may not read that as nothing
being wrong".

────────────────────────────────────────────────────────────────────────────────
evidence vs observed — why two dicts
────────────────────────────────────────────────────────────────────────────────

`evidence` is what the SOURCE says: stable, hashed into `evidence_sha`.
`observed` is what the READER measured at read time (ages, skews, HEAD sha):
volatile, never hashed.

Contract §4 lifts a fingerprint block when "the weakness's own evidence hash
changes". If `age_days` were inside the hash, every block would lift once a day
by the mere passage of time, which is a deduplicator that deduplicates nothing.

────────────────────────────────────────────────────────────────────────────────
NOT IN THIS MODULE, on purpose
────────────────────────────────────────────────────────────────────────────────

No verdict, no proposal, no budget, no judge, no scheduler, no write of any
kind. Nothing here accepts a value from the caller that can influence a
weakness's severity, title or evidence — the only inputs are FILTERS.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query

# Flat import, matching budget.py and ledger.py — Bone runs with its own
# directory on sys.path. Imported for ONE symbol: the repo-root resolver, so
# the reader and the judges cannot disagree about where the repo is again.
import judges

try:  # normal import (bone dir on sys.path)
    from loopauth import require_loop_scope
except ImportError:  # pragma: no cover — test loader path
    import importlib.util as _ilu

    _spec = _ilu.spec_from_file_location(
        "bone_loopauth", str(Path(__file__).with_name("loopauth.py"))
    )
    _mod = _ilu.module_from_spec(_spec)
    assert _spec is not None and _spec.loader is not None
    _spec.loader.exec_module(_mod)
    require_loop_scope = _mod.require_loop_scope

router = APIRouter(prefix="/api/v1/loop", tags=["loop"])


# ── Severity ────────────────────────────────────────────────────────────────

SEVERITIES = ("critical", "high", "medium", "low", "info")
_SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}


def normalize_severity(value: Any) -> str:
    s = str(value or "").strip().lower()
    return s if s in _SEV_RANK else "info"


# ── Freshness basis ─────────────────────────────────────────────────────────

BASIS_OBSERVED = "observed"
BASIS_MTIME = "filesystem_mtime"
BASIS_SELF_REPORTED = "self_reported"
BASIS_NONE = "none"
BASES = (BASIS_OBSERVED, BASIS_MTIME, BASIS_SELF_REPORTED, BASIS_NONE)


@dataclass
class Freshness:
    """How old a source is, and — load-bearing — WHO says so."""

    basis: str
    value: str | None = None
    #: Who wrote `value`. Mandatory for `self_reported`; that is the whole point.
    written_by: str | None = None
    #: An independent signal, if one exists at all.
    corroborator: str | None = None
    corroborated: bool | None = None
    corroborator_value: str | None = None
    skew_seconds: float | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.basis not in BASES:
            raise ValueError(f"unknown freshness basis: {self.basis}")
        if self.basis == BASIS_SELF_REPORTED and not self.written_by:
            # A self-report with no named author is an anonymous claim, which
            # is exactly the shape this module exists to refuse.
            raise ValueError("self_reported freshness must name written_by")

    @property
    def self_reported(self) -> bool:
        return self.basis == BASIS_SELF_REPORTED

    def to_dict(self) -> dict:
        d = asdict(self)
        d["self_reported"] = self.self_reported
        return d


# ── Weakness ────────────────────────────────────────────────────────────────


@dataclass
class Weakness:
    weakness_id: str
    source: str
    severity: str
    title: str
    #: What the SOURCE says. Hashed into evidence_sha. Must be JSON-canonical.
    evidence: dict = field(default_factory=dict)
    #: What the READER measured now. Never hashed.
    observed: dict = field(default_factory=dict)
    #: True when `severity` was computed from a value the source wrote about
    #: itself. The consumer must be able to see that the alarm and the thing it
    #: watches share an author.
    derived_from_self_report: bool = False
    #: True only when every REPO file this weakness's `evidence` was read from
    #: matches HEAD. The ledger keys the §4 retry ceiling on
    #: `(weakness_id, evidence_sha)`, and both are derived from file content —
    #: so a weakness minted by an UNCOMMITTED edit is a lift key the proposer
    #: wrote for itself. Set False by the source that read the file (it alone
    #: knows every path it touched); the reader still REPORTS the weakness,
    #: the ledger just refuses to let it key a ceiling (B4).
    evidence_committed: bool = True
    #: False when NO commit can ever satisfy the committed-evidence rule for
    #: this row — the evidence lives outside the repo (a firing alert, a
    #: pulse_runs row), not in a file somebody forgot to commit. Added
    #: 2026-09-03: all four withheld rows in the live `--gap` were alerts, and
    #: the single printed remedy — "commit docs/llm/security/" — was
    #: unsatisfiable for every one of them (docs/idea/19-fable-review-2.md
    #: named the class; nothing carried it to the tools). A reader branches:
    #: uncommitted-and-committable = commit it; uncommittable = observable,
    #: not proposable — it clears when the source clears.
    evidence_committable: bool = True

    def __post_init__(self) -> None:
        self.severity = normalize_severity(self.severity)

    @property
    def evidence_sha(self) -> str:
        blob = json.dumps(self.evidence, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "weakness_id": self.weakness_id,
            "source": self.source,
            "severity": self.severity,
            "title": self.title,
            "evidence": self.evidence,
            "evidence_sha": self.evidence_sha,
            "observed": self.observed,
            "derived_from_self_report": self.derived_from_self_report,
            "evidence_committed": self.evidence_committed,
            "evidence_committable": self.evidence_committable,
        }


STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"   # the source is not present on this host
STATUS_MALFORMED = "malformed"       # present, and it did not parse


@dataclass
class SourceReport:
    name: str
    status: str
    freshness: Freshness
    weaknesses: list[Weakness] = field(default_factory=list)
    path: str | None = None
    detail: str = ""
    #: Report-level twin of `Weakness.evidence_committed`, for weaknesses
    #: derived AFTER the source ran (`_freshness_weakness` reads the report's
    #: self-reported claim, which came out of the same file).
    evidence_committed: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "path": self.path,
            "weakness_count": len(self.weaknesses),
            "freshness": self.freshness.to_dict(),
            "detail": self.detail,
        }


# ── Paths ───────────────────────────────────────────────────────────────────


def repo_root() -> Path:
    """Repo the reader reads — delegated, so there is ONE answer.

    This module had the resolution right and `judges` inferred it from
    `__file__`; the two disagreed in the deployed daemon and the judge half was
    dead for it. Rather than keep two correct-looking copies, the resolver has
    one owner (`judges`, which budget and ledger already import) and this is a
    delegation. See `judges._default_repo_root`.
    """
    return judges._default_repo_root()


def state_dir() -> Path:
    """Runtime side-car (~/.nos). STATE_DIR is Bone's existing convention."""
    return Path(
        os.environ.get("NOS_LOOP_STATE_DIR")
        or os.environ.get("STATE_DIR")
        or (Path.home() / ".nos")
    ).expanduser()


#: Documented drift threshold for the security scan (CLAUDE.md: ">14 days = drift
#: hook starts complaining"). Doctrine, not taste — hence a constant, not a var.
SCAN_STALE_DAYS = int(os.environ.get("BONE_LOOP_SCAN_STALE_DAYS", "14"))

#: How far the self-report and its corroborator may diverge before the
#: divergence is itself reportable. Generous: batch writers are not atomic.
CORROBORATION_TOLERANCE_S = 6 * 3600

_MAX_TEXT = 400
_MAX_LIST = 25


# ── Small parsers ───────────────────────────────────────────────────────────


def parse_iso(value: Any) -> datetime | None:
    """Parse BOTH ISO-8601 spellings this estate emits, and fail soft.

    `scan-state.json` is written by two processes: `scan-runner.sh` emits jq's
    trailing-`Z` form, the security agent emits local time with a numeric
    offset. Consumers that accepted only the `Z` form made the nightly drift
    watcher produce no verdict at all, silently, at exit 0, for its entire life
    (gate: tests/anatomy/test_drift_check_parses_both_iso_spellings.py). Both
    spellings parse here, and anything unparseable returns None rather than
    raising — a reader that dies on one bad timestamp reports nothing at all.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_days(dt: datetime | None) -> float | None:
    return None if dt is None else round((_now() - dt).total_seconds() / 86400.0, 2)


def _clip(text: Any, limit: int = _MAX_TEXT) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _first_clause(text: Any, limit: int = 140) -> str:
    s = " ".join(str(text or "").split())
    for sep in (" | ", ". "):
        idx = s.find(sep)
        if 0 < idx < limit:
            s = s[:idx]
            break
    return _clip(s, limit)


def _read_json(path: Path) -> tuple[str, Any, str]:
    """(status, data, detail). Never raises; absence and garbage are distinct."""
    if not path.is_file():
        return STATUS_UNAVAILABLE, None, f"{path} does not exist"
    try:
        return STATUS_OK, json.loads(path.read_text(encoding="utf-8")), ""
    except (OSError, ValueError) as exc:
        return STATUS_MALFORMED, None, f"{type(exc).__name__}: {exc}"


def _mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def _unavailable(
    name: str,
    *,
    required: bool,
    path: Path | None,
    status: str,
    detail: str,
    evidence_committed: bool = True,
) -> SourceReport:
    """A source that could not be read reports a WEAKNESS, never silence.

    `malformed` outranks `unavailable`: a file that is present and unparseable
    is a defect wherever it lives, while an absent optional file may simply mean
    the organ was never installed on this host.

    `evidence_committed=False` when the unreadability itself is an uncommitted
    state — an in-repo source file DELETED or mangled in the working tree only.
    Deleting a ledger is as good a mint as appending to one: it produces this
    very `source:<name>:<status>` weakness, which must not key a retry ceiling.
    """
    if status == STATUS_MALFORMED:
        severity = "high"
        title = f"weakness source '{name}' is present but did not parse"
    else:
        severity = "medium" if required else "info"
        title = f"weakness source '{name}' is unreadable — this list is incomplete"
    return SourceReport(
        name=name,
        status=status,
        path=str(path) if path else None,
        detail=detail,
        evidence_committed=evidence_committed,
        freshness=Freshness(
            basis=BASIS_NONE,
            note="source did not report; no freshness signal available",
        ),
        weaknesses=[
            Weakness(
                weakness_id=f"source:{name}:{status}",
                source=name,
                severity=severity,
                title=title,
                evidence={
                    "source": name,
                    "status": status,
                    "required": required,
                    "path": str(path) if path else None,
                    "detail": _clip(detail),
                },
                observed={
                    "consequence": (
                        "weaknesses this source would have reported are ABSENT "
                        "from the list; absence here is not evidence of health"
                    )
                },
                evidence_committed=evidence_committed,
            )
        ],
    )


# ── Source 1: the git working tree ──────────────────────────────────────────

#: Repo paths a SCHEDULED JOB writes. An uncommitted change to one of these is
#: not an operator edit in progress — it is a job whose output never reached the
#: place its consumers read from. Data, so a test can read it.
MACHINE_WRITTEN: dict[str, str] = {
    "docs/llm/security/remediation-queue.json": "the nightly security scan",
    "docs/llm/security/scan-state.json": "the nightly security scan",
    "docs/llm/security/versions.json": "the nightly security scan",
    "docs/llm/security/misconfig-findings.json": "the nightly security scan",
    "docs/llm/security/attack-surface.json": "the nightly security scan",
    "docs/llm/security/pentest-journal.json": "the pentest agent",
    "docs/llm/security/audit-manifest.json": "the security audit agent",
    "state/devlog-bundle.jsonl": "tools/devlog-compile.py",
    "state/tofu-authentik-services.yml": "tools/tofu-authentik-gen-registry.py",
    "files/anatomy/module_utils/nos_entity.py": "tools/genome-codegen.py",
    "files/anatomy/face/src/lib/contracts/entity.gen.ts": "tools/genome-codegen.py",
}


def _git(root: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(  # noqa: S603 — list form, shell=False
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return proc.returncode, proc.stdout


def _parse_porcelain_z(blob: str) -> list[tuple[str, str]]:
    """[(xy, path)] from `git status --porcelain=v1 -z`.

    Rename/copy entries carry TWO NUL-separated paths; the second is the old
    name and must be consumed or every subsequent entry shifts by one.
    """
    tokens = [t for t in blob.split("\0") if t != ""]
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(tokens):
        entry = tokens[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        if xy[0] in ("R", "C"):
            i += 1  # consume the old name
        out.append((xy, path))
    return out


def _source_git_worktree() -> tuple[SourceReport, set[str]]:
    """Uncommitted work, ranked by who wrote it. Returns (report, dirty paths).

    Freshness is `observed`: the reader ran git itself, so nothing here is a
    claim by the thing being measured. This is the one source that structurally
    cannot self-report.
    """
    name = "git-worktree"
    root = repo_root()

    rc, out = _git(root, "rev-parse", "--show-toplevel")
    if rc != 0:
        return (
            _unavailable(
                name,
                required=True,
                path=root,
                status=STATUS_UNAVAILABLE,
                detail=f"not a git repository (or git unavailable): {_clip(out)}",
            ),
            set(),
        )
    toplevel = out.strip() or str(root)

    rc, status_blob = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if rc != 0:
        return (
            _unavailable(
                name,
                required=True,
                path=root,
                status=STATUS_MALFORMED,
                detail=f"git status failed: {_clip(status_blob)}",
            ),
            set(),
        )

    _, head_out = _git(root, "rev-parse", "HEAD")
    head_sha = head_out.strip() or None

    entries = _parse_porcelain_z(status_blob)
    dirty = {p for _, p in entries}

    # One numstat call for the whole tree beats one per file.
    _, numstat_blob = _git(root, "diff", "--numstat", "HEAD", "--")
    numstat: dict[str, str] = {}
    for line in numstat_blob.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            numstat[parts[2]] = f"+{parts[0]}/-{parts[1]}"

    weaknesses: list[Weakness] = []
    machine: list[tuple[str, str, str]] = []   # (path, xy, writer)
    tracked: list[tuple[str, str]] = []
    untracked: list[str] = []

    for xy, path in sorted(entries, key=lambda e: e[1]):
        # Machine-written first, INCLUDING when untracked: a scheduled job whose
        # output was never added is the same failure as one never committed.
        if path in MACHINE_WRITTEN:
            machine.append((path, xy, MACHINE_WRITTEN[path]))
        elif xy == "??":
            untracked.append(path)
        else:
            tracked.append((path, xy))

    # ── requirement 1: one weakness PER machine-written path, named writer ──
    # Every weakness of this source carries evidence_committed=False: its
    # evidence IS the uncommitted state of the tree, i.e. exactly the thing a
    # proposer can change at will with one `touch`. Reporting it is this
    # source's whole job; letting it key a §4 retry ceiling would hand the
    # blocked party a self-service lift key (B4).
    for path, xy, writer in machine:
        weaknesses.append(
            Weakness(
                weakness_id=f"git:uncommitted:{path}",
                source=name,
                severity="high",
                evidence_committed=False,
                title=(
                    f"{path} was written by {writer} and is not committed — "
                    "every consumer that reads HEAD sees the older file"
                ),
                evidence={
                    "path": path,
                    "porcelain_xy": xy,
                    "writer": writer,
                    "numstat": numstat.get(path, "untracked"),
                    "machine_written": True,
                },
                observed={
                    "head_sha": head_sha,
                    "consequence": (
                        "CI, a converge and any HEAD-based reader are working "
                        "from a different file than the one on disk"
                    ),
                },
            )
        )

    if tracked:
        weaknesses.append(
            Weakness(
                weakness_id="git:uncommitted-tracked",
                source=name,
                severity="medium",
                evidence_committed=False,
                title=f"{len(tracked)} tracked file(s) modified but not committed",
                evidence={
                    "count": len(tracked),
                    "paths": [p for p, _ in tracked[:_MAX_LIST]],
                    "truncated": len(tracked) > _MAX_LIST,
                },
                observed={"head_sha": head_sha},
            )
        )

    if untracked:
        weaknesses.append(
            Weakness(
                weakness_id="git:untracked",
                source=name,
                severity="low",
                evidence_committed=False,
                title=f"{len(untracked)} untracked file(s) in the working tree",
                evidence={
                    "count": len(untracked),
                    "paths": sorted(untracked)[:_MAX_LIST],
                    "truncated": len(untracked) > _MAX_LIST,
                },
                observed={"head_sha": head_sha},
            )
        )

    return (
        SourceReport(
            name=name,
            status=STATUS_OK,
            path=toplevel,
            freshness=Freshness(
                basis=BASIS_OBSERVED,
                value=_now().isoformat(),
                note="the reader ran git itself; nothing here is self-reported",
            ),
            weaknesses=weaknesses,
            detail=f"{len(entries)} changed path(s)",
            evidence_committed=False,  # this source reports the worktree itself
        ),
        dirty,
    )


def _git_state(path_rel: str, dirty: set[str]) -> str:
    return "modified-uncommitted" if path_rel in dirty else "matches-HEAD"


# ── Corroborator: the append-only scan event log ────────────────────────────


def _last_scan_event() -> tuple[str | None, str]:
    """(iso ts of the last `scan.batch_done`, note). Independent of the scanner.

    `~/.nos/events/scan.jsonl` is append-only and written per batch. It is not
    the scanner's opinion of its own freshness — it is a record of batches that
    finished. That distinction is the entire reason this function exists.
    """
    path = state_dir() / "events" / "scan.jsonl"
    if not path.is_file():
        return None, f"{path} absent — no independent record of scan runs"
    latest: datetime | None = None
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or "scan.batch_done" not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") != "scan.batch_done":
                continue
            dt = parse_iso(row.get("ts"))
            if dt and (latest is None or dt > latest):
                latest = dt
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if latest is None:
        return None, "no scan.batch_done events recorded"
    return latest.isoformat(), "last scan.batch_done in the append-only event log"


def _corroborate(claim: str | None, observed: str | None) -> tuple[bool | None, float | None]:
    """(corroborated, skew_seconds). None when there is nothing to compare to."""
    c, o = parse_iso(claim), parse_iso(observed)
    if c is None or o is None:
        return None, None
    skew = (c - o).total_seconds()
    return abs(skew) <= CORROBORATION_TOLERANCE_S, round(skew, 1)


# ── Source 2: the security remediation queue ────────────────────────────────

REMEDIATION_REL = "docs/llm/security/remediation-queue.json"


def _source_remediation_queue(dirty: set[str]) -> SourceReport:
    name = "remediation-queue"
    path = repo_root() / REMEDIATION_REL
    committed = REMEDIATION_REL not in dirty
    status, data, detail = _read_json(path)
    if status != STATUS_OK or not isinstance(data, dict):
        return _unavailable(
            name,
            required=True,
            path=path,
            status=status if status != STATUS_OK else STATUS_MALFORMED,
            detail=detail or "top level is not an object",
            evidence_committed=committed,
        )

    items = data.get("items")
    if not isinstance(items, list):
        return _unavailable(
            name, required=True, path=path, status=STATUS_MALFORMED,
            detail="items[] missing or not a list",
            evidence_committed=committed,
        )

    git_state = _git_state(REMEDIATION_REL, dirty)
    weaknesses: list[Weakness] = []

    # ── pending items. Severity is gated on status: 37 CRITICAL exist in this
    # file and ZERO of them are pending, so severity alone is the wrong key.
    for item in items:
        if not isinstance(item, dict) or item.get("status") != "pending":
            continue
        rid = str(item.get("id") or "REM-?")
        component = str(item.get("component") or "unknown")
        rtype = str(item.get("remediation_type") or "remediation")
        weaknesses.append(
            Weakness(
                weakness_id=f"rem:{rid}",
                source=name,
                severity=normalize_severity(item.get("severity")),
                title=f"{component}: {rtype} — {_first_clause(item.get('remediation_detail'))}",
                evidence={
                    "id": rid,
                    "finding_ref": item.get("finding_ref"),
                    "component": component,
                    "remediation_type": rtype,
                    "current_version": item.get("current_version"),
                    "fix_version": item.get("fix_version"),
                    "found_at": item.get("found_at"),
                    "scan_cycle": item.get("scan_cycle"),
                    "scan_source": item.get("source"),
                    "confidence": item.get("confidence"),
                    "remediation_detail": _clip(item.get("remediation_detail")),
                    "file": REMEDIATION_REL,
                },
                observed={"file_git_state": git_state},
                evidence_committed=committed,
            )
        )

    # ── integrity: the hand-maintained summary vs the items it summarises.
    # Measured at HEAD on 2026-08-01: summary claimed resolved 121 / pending 19
    # while items[] gave 128 / 12 — wrong by 7 in BOTH directions. Derive from
    # items[]; report the disagreement rather than silently preferring one.
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    recomputed: dict[str, int] = {}
    for item in items:
        if isinstance(item, dict):
            key = str(item.get("status") or "unknown")
            recomputed[key] = recomputed.get(key, 0) + 1
    claimed = summary.get("by_status") if isinstance(summary.get("by_status"), dict) else None
    if claimed is not None and {k: int(v) for k, v in claimed.items()} != recomputed:
        deltas = {
            k: int(claimed.get(k, 0)) - recomputed.get(k, 0)
            for k in sorted(set(claimed) | set(recomputed))
            if int(claimed.get(k, 0)) != recomputed.get(k, 0)
        }
        weaknesses.append(
            Weakness(
                weakness_id="rem:summary-disagrees-with-items",
                source=name,
                severity="medium",
                title=(
                    "remediation-queue summary.by_status disagrees with its own "
                    "items[] — a hand-maintained count nobody recomputes"
                ),
                evidence={
                    "file": REMEDIATION_REL,
                    "claimed_by_status": {k: int(v) for k, v in sorted(claimed.items())},
                    "recomputed_by_status": dict(sorted(recomputed.items())),
                    "deltas": deltas,
                },
                observed={
                    "file_git_state": git_state,
                    "rule": "derive counts from items[], never from summary",
                },
                evidence_committed=committed,
            )
        )

    claim = data.get("generated_at")
    corroborator_value, corroborator_note = _last_scan_event()
    corroborated, skew = _corroborate(claim, corroborator_value)
    return SourceReport(
        name=name,
        status=STATUS_OK,
        path=str(path),
        evidence_committed=committed,
        detail=f"{len(items)} items, {len([w for w in weaknesses if w.weakness_id.startswith('rem:REM-')])} pending",
        freshness=Freshness(
            basis=BASIS_SELF_REPORTED,
            value=str(claim) if claim else None,
            written_by="the security scan agent that writes this file",
            corroborator=corroborator_note,
            corroborator_value=corroborator_value,
            corroborated=corroborated,
            skew_seconds=skew,
            note=(
                "`generated_at` was measured byte-identical across a change that "
                "ADDED items — the field does not reliably advance with content"
            ),
        ),
        weaknesses=weaknesses,
    )


# ── Source 3: security scan freshness ───────────────────────────────────────

SCAN_STATE_REL = "docs/llm/security/scan-state.json"


def _source_scan_state(dirty: set[str]) -> SourceReport:
    """THE canonical self-reporting source. Every severity here is marked.

    `last_full_scan` is written BY the scan it describes; `components.<n>.status
    = "scanned"` is stamped by the agent claiming to have scanned. Neither is
    evidence that a scan happened, and this reader never presents them as such —
    it presents them next to `scan.jsonl`, which is written per finished batch.
    """
    name = "scan-state"
    path = repo_root() / SCAN_STATE_REL
    committed = SCAN_STATE_REL not in dirty
    status, data, detail = _read_json(path)
    if status != STATUS_OK or not isinstance(data, dict):
        return _unavailable(
            name,
            required=True,
            path=path,
            status=status if status != STATUS_OK else STATUS_MALFORMED,
            detail=detail or "top level is not an object",
            evidence_committed=committed,
        )

    git_state = _git_state(SCAN_STATE_REL, dirty)
    claim = data.get("last_full_scan")
    claim_dt = parse_iso(claim)
    corroborator_value, corroborator_note = _last_scan_event()
    corroborated, skew = _corroborate(claim, corroborator_value)
    age = _age_days(claim_dt)

    weaknesses: list[Weakness] = []

    if claim_dt is None:
        weaknesses.append(
            Weakness(
                weakness_id="scan:last-full-scan-unparseable",
                source=name,
                severity="high",
                title="scan-state.last_full_scan is missing or unparseable",
                evidence={"file": SCAN_STATE_REL, "raw_value": _clip(claim, 80)},
                observed={
                    "file_git_state": git_state,
                    "note": (
                        "two writers emit two ISO-8601 spellings; a consumer that "
                        "accepts only one produces no verdict at all, at exit 0"
                    ),
                },
                evidence_committed=committed,
            )
        )
    elif age is not None and age > SCAN_STALE_DAYS:
        weaknesses.append(
            Weakness(
                weakness_id="scan:stale-full-scan",
                source=name,
                severity="high" if age > SCAN_STALE_DAYS * 2 else "medium",
                title=(
                    f"security scan is {age:.1f} days old "
                    f"(threshold {SCAN_STALE_DAYS}) — per the file's own claim"
                ),
                # SELF-REPORTED: the severity above is computed from a value the
                # scan wrote about itself. Marked, and shipped with its corroborator.
                derived_from_self_report=True,
                evidence={
                    "file": SCAN_STATE_REL,
                    "last_full_scan": str(claim),
                    "scan_cycle": data.get("scan_cycle"),
                    "threshold_days": SCAN_STALE_DAYS,
                },
                observed={
                    "age_days": age,
                    "file_git_state": git_state,
                    "corroborator": corroborator_note,
                    "corroborator_value": corroborator_value,
                    "corroborated": corroborated,
                    "warning": (
                        "this severity is derived from a timestamp written by the "
                        "scan it describes — the alarm and the thing it watches "
                        "share an author"
                    ),
                },
                evidence_committed=committed,
            )
        )

    # NB: an uncorroborated `last_full_scan` is NOT handled here. It is one
    # instance of a general shape — a self-report contradicted by an
    # independent signal — and `_freshness_weakness` below emits it for EVERY
    # self-reporting source, in one place. Patching it per source is how the
    # third source ends up with no check at all.

    components = data.get("components") if isinstance(data.get("components"), dict) else {}
    never = sorted(
        cname
        for cname, c in components.items()
        if isinstance(c, dict) and not c.get("last_checked")
    )
    if never:
        weaknesses.append(
            Weakness(
                weakness_id="scan:components-never-checked",
                source=name,
                severity="info",
                title=f"{len(never)} component(s) have no last_checked timestamp",
                evidence={
                    "file": SCAN_STATE_REL,
                    "count": len(never),
                    "components": never[:_MAX_LIST],
                    "truncated": len(never) > _MAX_LIST,
                },
                observed={"file_git_state": git_state},
                evidence_committed=committed,
            )
        )

    return SourceReport(
        name=name,
        status=STATUS_OK,
        path=str(path),
        evidence_committed=committed,
        detail=f"cycle {data.get('scan_cycle')}, {len(components)} components",
        freshness=Freshness(
            basis=BASIS_SELF_REPORTED,
            value=str(claim) if claim else None,
            written_by="the security scan itself (scan-runner.sh / the security agent)",
            corroborator=corroborator_note,
            corroborator_value=corroborator_value,
            corroborated=corroborated,
            skew_seconds=skew,
            note=(
                "components.<n>.status='scanned' is stamped by the agent claiming "
                "to have scanned; it is never treated as evidence a scan happened"
            ),
        ),
        weaknesses=weaknesses,
    )


# ── Source 4: the hidden-fees ledger ────────────────────────────────────────

FEES_REL = "docs/hidden_fees/README.md"

_FEE_ROW = re.compile(
    r"^\|\s*\[(?P<num>\d+)\]\((?P<file>[^)]+)\)\s*\|(?P<fee>[^|]*)\|(?P<bill>[^|]*)\|(?P<status>[^|]*)\|\s*$"
)
_FILE_STATUS = re.compile(r"^\*\*Status:\*\*\s*(?P<status>.+?)\s*$", re.MULTILINE)


def _clean_cell(text: str) -> str:
    """Strip the index table's markdown emphasis and strike-through."""
    return " ".join(text.replace("~~", "").replace("**", "").split()).strip()


def _fee_state(status_cell: str) -> str:
    """open | partly | closed. The status column is free text; normalise once."""
    s = _clean_cell(status_cell).lower()
    if s.startswith("partly"):
        return "partly"
    if "closed" in s:
        return "closed"
    return "open"


#: state + bill phrasing -> severity. Declared as data because the mapping is a
#: judgement call and a reader that hides its judgement calls is worse than one
#: that states them. `09` says its bill is "being paid now" — a fee already
#: being charged outranks a conditional one.
def _fee_severity(state: str, bill: str, status: str) -> str:
    text = f"{bill} {status}".lower()
    if state == "closed":
        return "info"
    if "being paid now" in text or "paid)" in text:
        return "high"
    if state == "partly":
        return "low"
    return "medium"


def _fee_body(path: Path) -> str:
    """The '## The fee' paragraph, bounded. Absent in no file measured, but
    treated as optional anyway — a missing heading must not drop the row."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## the fee"):
            body: list[str] = []
            for nxt in lines[i + 1 :]:
                if nxt.startswith("## "):
                    break
                if nxt.strip():
                    body.append(nxt.strip())
                elif body:
                    break
            return _clip(" ".join(body))
    return ""


def _source_hidden_fees(dirty: set[str]) -> SourceReport:
    name = "hidden-fees"
    root = repo_root()
    path = root / FEES_REL
    index_committed = FEES_REL not in dirty
    if not path.is_file():
        return _unavailable(
            name, required=True, path=path, status=STATUS_UNAVAILABLE,
            detail=f"{path} does not exist",
            evidence_committed=index_committed,
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return _unavailable(
            name, required=True, path=path, status=STATUS_MALFORMED,
            detail=f"{type(exc).__name__}: {exc}",
            evidence_committed=index_committed,
        )

    rows = [m for m in (_FEE_ROW.match(ln) for ln in text.splitlines()) if m]
    if not rows:
        # Absence is never success: an index that parses to zero rows is a
        # parser/format divergence, not thirteen closed fees.
        return _unavailable(
            name, required=True, path=path, status=STATUS_MALFORMED,
            detail="index table parsed to zero rows — format drift",
            evidence_committed=index_committed,
        )

    git_state = _git_state(FEES_REL, dirty)
    weaknesses: list[Weakness] = []
    open_count = 0

    for m in rows:
        num = m.group("num")
        rel_file = m.group("file")
        state = _fee_state(m.group("status"))
        if state == "closed":
            continue
        open_count += 1
        fee = _clean_cell(m.group("fee"))
        bill = _clean_cell(m.group("bill"))
        status_cell = _clean_cell(m.group("status"))
        fee_path = f"docs/hidden_fees/{rel_file}"
        # Evidence is read from TWO files: the index row and the fee file's
        # own "## The fee" body. Either one edited uncommitted can mint a new
        # weakness_id or move `evidence_sha` — both are §4 ceiling keys.
        fee_committed = index_committed and fee_path not in dirty
        weaknesses.append(
            Weakness(
                weakness_id=f"fee:{num}",
                source=name,
                severity=_fee_severity(state, bill, status_cell),
                title=fee,
                evidence_committed=fee_committed,
                evidence={
                    "number": num,
                    "file": fee_path,
                    "bill_comes_due_when": bill,
                    "index_status": status_cell,
                    "state": state,
                    "the_fee": _fee_body(root / "docs" / "hidden_fees" / rel_file),
                },
                observed={
                    "index_file_git_state": git_state,
                    "authority": "the README index table (only 3 of 13 files carry a Status line)",
                },
            )
        )

        # Integrity: where a file DOES carry its own Status, disagreement with
        # the index is a real defect — two hand-maintained surfaces, no gate.
        own = _FILE_STATUS.search(_safe_read(root / "docs" / "hidden_fees" / rel_file))
        if own and _fee_state(own.group("status")) != state:
            weaknesses.append(
                Weakness(
                    weakness_id=f"fee:{num}:status-disagrees",
                    source=name,
                    severity="medium",
                    evidence_committed=fee_committed,
                    title=f"hidden fee {num}: the file's Status disagrees with the index",
                    evidence={
                        "number": num,
                        "file": fee_path,
                        "index_status": status_cell,
                        "file_status": _clean_cell(own.group("status")),
                    },
                    observed={"index_file_git_state": git_state},
                )
            )

    return SourceReport(
        name=name,
        status=STATUS_OK,
        path=str(path),
        evidence_committed=index_committed,
        detail=f"{len(rows)} rows, {open_count} not closed",
        freshness=Freshness(
            basis=BASIS_SELF_REPORTED,
            value=None,
            written_by="whoever last edited the table by hand",
            corroborator=None,
            corroborated=None,
            note=(
                "no timestamp and no gate ties a 'closed' row to the gate that "
                "closed it; the index and the files are edited independently"
            ),
        ),
        weaknesses=weaknesses,
    )


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


# ── Source 5: the cortex corpus-diff ledger ─────────────────────────────────


def _source_corpus_diff(dirty: set[str]) -> SourceReport:
    """Host-state, not repo-state: absent is legitimate on a host without KEAP,
    so this source is `required=False` — but absence still speaks."""
    name = "corpus-diff"
    path = state_dir() / "cortex-corpus-diff.json"
    status, data, detail = _read_json(path)
    if status != STATUS_OK or not isinstance(data, dict):
        return _unavailable(
            name,
            required=False,
            path=path,
            status=status if status != STATUS_OK else STATUS_MALFORMED,
            detail=detail or "top level is not an object",
        )

    nights = data.get("nights") if isinstance(data.get("nights"), list) else []
    weaknesses: list[Weakness] = []

    if data.get("halted"):
        weaknesses.append(
            Weakness(
                weakness_id="corpus:halted",
                source=name,
                severity="critical",
                # Says "is refusing", not "was stopped". Until 2026-08-06 the
                # past tense described an act nothing performed: the flag was
                # set, no halt command was ever configured, and fs-sync walked
                # on. The present tense is now true of every pass while the
                # flag stands (cortex-fs-sync.py exits 4), and it stays true
                # until someone runs --clear-halt.
                title="corpus-diff is HALTED — the organ's fs-sync is refusing to walk",
                evidence={"file": str(path), "halted": True},
                observed={},
            )
        )

    if not nights:
        # The ledger exists and has recorded nothing. `night VOID` exits 0 in the
        # script itself, which is the same absence-reads-as-success shape.
        weaknesses.append(
            Weakness(
                weakness_id="corpus:no-nights-recorded",
                source=name,
                severity="medium",
                title="corpus-diff ledger exists but has never recorded a night",
                evidence={"file": str(path), "nights": 0},
                observed={
                    "note": "an empty comparison is not an agreeing comparison"
                },
            )
        )
        last_at = None
    else:
        last = nights[-1] if isinstance(nights[-1], dict) else {}
        last_at = last.get("at")
        result = str(last.get("result") or "unknown").lower()
        if result != "agree":
            clauses = last.get("clauses") if isinstance(last.get("clauses"), dict) else {}
            weaknesses.append(
                Weakness(
                    weakness_id="corpus:last-night-disagrees",
                    source=name,
                    severity="high" if result == "disagree" else "medium",
                    title=f"corpus-diff last night reported '{result}', not agreement",
                    evidence={
                        "file": str(path),
                        "at": last_at,
                        "result": result,
                        "failing_clauses": sorted(
                            k for k, v in clauses.items() if v is not True
                        ),
                    },
                    observed={"agree_streak": data.get("agreeStreak")},
                )
            )

    mtime = _mtime_iso(path)
    corroborated, skew = _corroborate(last_at, mtime)
    return SourceReport(
        name=name,
        status=STATUS_OK,
        path=str(path),
        detail=f"{len(nights)} nights, agreeStreak={data.get('agreeStreak')}",
        freshness=Freshness(
            basis=BASIS_SELF_REPORTED,
            value=str(last_at) if last_at else None,
            written_by="cortex-corpus-diff.py, which writes this ledger",
            corroborator="filesystem mtime of the ledger",
            corroborator_value=mtime,
            corroborated=corroborated,
            skew_seconds=skew,
            note="a VOID night (organ unreachable) exits 0 in the script itself",
        ),
        weaknesses=weaknesses,
    )


# ── Registry + ranking ──────────────────────────────────────────────────────

# ── Source 6: Prometheus firing alerts ──────────────────────────────────────
#
# THE ONLY LIVE SIGNAL IN THIS READER, and it was missing until 2026-08-05.
# Every source above reads a file, which makes them reproducible and makes this
# reader blind to anything the estate notices at runtime. Measured that day:
# five `NosWarningServiceDegraded` alerts had been firing since 2026-07-26 and
# appeared in no queue, no fee, and no ledger.
#
# EVIDENCE IS THE IDENTITY, NOT THE READING. `evidence` holds only the alert
# name and its labels, so the hash is stable while the alert keeps firing. The
# value, the state and `activeAt` go in `observed`, which is never hashed. An
# alert whose evidence changed every scrape would mint a fresh §4 retry-ceiling
# key on every poll, which is the grinding this engine exists to prevent.
#
# NOT COMMITTABLE, AND THAT IS THE POINT. `evidence_committed=False`: there is
# no repo file behind a live alert, so the ledger will REPORT it and refuse to
# let it key a ceiling. Observable, not proposable — stated here rather than
# discovered later by a proposer whose 201 turns into a 409.

_PROM_SEVERITY = {
    "critical": "critical", "high": "high", "error": "high",
    "warning": "medium", "medium": "medium",
    "info": "info", "low": "low",
}


def _source_prometheus_alerts(dirty: set[str]) -> SourceReport:
    name = "prometheus-alerts"
    base = os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9090").rstrip("/")
    try:
        req = urllib.request.Request(f"{base}/api/v1/alerts",
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — unreachable is a legitimate host state
        return _unavailable(
            name, required=False, path=None, status=STATUS_UNAVAILABLE,
            detail=f"{base} not reachable: {type(exc).__name__}: {exc}",
            evidence_committed=False,
        )
    if payload.get("status") != "success":
        return _unavailable(
            name, required=False, path=None, status=STATUS_MALFORMED,
            detail=f"prometheus returned status={payload.get('status')!r}",
            evidence_committed=False,
        )

    alerts = payload.get("data", {}).get("alerts", []) or []
    firing = [a for a in alerts if a.get("state") == "firing"]
    weaknesses: list[Weakness] = []
    for alert in firing:
        labels = alert.get("labels", {}) or {}
        ann = alert.get("annotations", {}) or {}
        alertname = str(labels.get("alertname") or "UnnamedAlert")
        ident = hashlib.sha256(
            json.dumps(labels, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:8]
        target = labels.get("service") or labels.get("instance") or labels.get("job") or ""
        weaknesses.append(Weakness(
            weakness_id=f"alert:{alertname}:{ident}",
            source=name,
            severity=_PROM_SEVERITY.get(str(labels.get("severity", "")).lower(), "medium"),
            title=f"{alertname} firing{f' — {target}' if target else ''}",
            evidence={"alertname": alertname, "labels": labels},
            observed={
                "active_at": alert.get("activeAt"),
                "value": alert.get("value"),
                "summary": _clip(ann.get("summary") or ann.get("description")),
                "runbook_url": ann.get("runbook_url"),
            },
            evidence_committed=False,
            evidence_committable=False,
        ))

    return SourceReport(
        name=name,
        status=STATUS_OK,
        # `observed`: this reader queried the server itself just now. No
        # self-report to distrust, and nothing to corroborate it against.
        freshness=Freshness(basis=BASIS_OBSERVED, value=_now().isoformat(),
                            note=f"{len(alerts)} alert(s) known, {len(firing)} firing"),
        weaknesses=weaknesses,
        path=f"{base}/api/v1/alerts",
        evidence_committed=False,
    )


# ── Source 7: pulse runs that failed ────────────────────────────────────────
#
# The scheduler records every run's exit code and nothing reads them for defect
# purposes. Measured 2026-08-05: gitleaks and keap-features-sync had each
# failed 3 times in the preceding fortnight and the tofu drift plan once —
# visible only to an operator running SQL by hand.
#
# LATEST RUN ONLY, plus the streak. A job that failed a week ago and has
# succeeded nightly since is not a present defect; reporting it would fill the
# list with history and teach a reader to skim it.

_PULSE_STREAK_DEPTH = 20


def _source_pulse_runs(dirty: set[str]) -> SourceReport:
    name = "pulse-runs"
    db_path = Path(os.environ.get(
        "WING_DB_PATH", os.path.expanduser("~/wing/app/data/wing.db")))
    if not db_path.is_file():
        return _unavailable(
            name, required=False, path=db_path, status=STATUS_UNAVAILABLE,
            detail="wing.db not present — Wing has not been provisioned here",
            evidence_committed=False,
        )
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            # A FINDING IS NOT A FAILURE, and the job table already says which
            # codes mean which. `discovery:contradiction-scan` declares [1] and
            # `loop:propose` declares [1,3] — both exit 1 to say "I found
            # something", both were being mined here as red, and a streak of
            # three ratchets that to HIGH. Measured 2026-08-30: of six jobs
            # this source called failed, two had succeeded, and one of them was
            # the LOOP'S OWN ENTRY — so the loop reported itself as a HIGH
            # weakness its own deny rule forbids it from proposing against.
            # Same defect as hidden fee 34, one reader over.
            findings = {}
            for job in conn.execute(
                "SELECT id, findings_exit_codes FROM pulse_jobs "
                "WHERE findings_exit_codes IS NOT NULL"
            ).fetchall():
                try:
                    codes = json.loads(job["findings_exit_codes"] or "[]")
                except (TypeError, ValueError):
                    continue  # a malformed declaration must not silence a red job
                if isinstance(codes, list):
                    findings[job["id"]] = {int(c) for c in codes
                                           if isinstance(c, (int, str)) and str(c).lstrip("-").isdigit()}

            def _is_failure(job_id: str, code: object) -> bool:
                """Red means red. Not null, not zero, not a declared finding."""
                return (code is not None and code != 0
                        and int(code) not in findings.get(job_id, set()))

            rows = [r for r in conn.execute(
                """
                SELECT job_id, exit_code, fired_at, stderr_tail
                  FROM (SELECT job_id, exit_code, fired_at, stderr_tail,
                               ROW_NUMBER() OVER (PARTITION BY job_id
                                                  ORDER BY fired_at DESC) AS rn
                          FROM pulse_runs)
                 WHERE rn = 1 AND exit_code IS NOT NULL AND exit_code <> 0
                """
            ).fetchall() if _is_failure(r["job_id"], r["exit_code"])]
            streaks = {}
            for row in rows:
                recent = conn.execute(
                    "SELECT exit_code FROM pulse_runs WHERE job_id = ? "
                    "ORDER BY fired_at DESC LIMIT ?",
                    (row["job_id"], _PULSE_STREAK_DEPTH),
                ).fetchall()
                streak = 0
                for r in recent:
                    # A findings run breaks the streak exactly as a green one
                    # does — otherwise a job that finds something every night
                    # ratchets to HIGH for working.
                    if not _is_failure(row["job_id"], r["exit_code"]):
                        break
                    streak += 1
                streaks[row["job_id"]] = streak
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return _unavailable(
            name, required=False, path=db_path, status=STATUS_MALFORMED,
            detail=f"wing.db read failed: {exc}", evidence_committed=False,
        )

    weaknesses = []
    for row in rows:
        streak = streaks.get(row["job_id"], 1)
        weaknesses.append(Weakness(
            weakness_id=f"pulse:{row['job_id']}",
            source=name,
            # A single red run is a blip worth seeing; a streak is a job that
            # has stopped working and nobody noticed.
            severity="high" if streak >= 3 else "medium",
            title=f"pulse job {row['job_id']} last exited {row['exit_code']}"
                  + (f" ({streak} consecutive failures)" if streak > 1 else ""),
            evidence={"job_id": row["job_id"], "exit_code": row["exit_code"],
                      "consecutive_failures": streak},
            observed={"fired_at": row["fired_at"],
                      "stderr_tail": _clip(row["stderr_tail"], 400)},
            evidence_committed=False,
            evidence_committable=False,
        ))

    return SourceReport(
        name=name,
        status=STATUS_OK,
        freshness=Freshness(basis=BASIS_OBSERVED, value=_now().isoformat(),
                            note=f"{len(weaknesses)} job(s) whose latest run failed"),
        weaknesses=weaknesses,
        path=str(db_path),
        evidence_committed=False,
    )


#: Source order IS the primary ranking key. Contract §9.1 leaves the ranking
#: FUNCTION deliberately undecided ("v1 groups by source and sorts by severity
#: within it"), so this is v1, stated as data rather than emerging from dict
#: iteration order. git-worktree leads because it is the finding with no other
#: reporter: every other source here has a file, a queue or a gate somewhere
#: else that also mentions it.
SOURCE_ORDER: tuple[str, ...] = (
    "git-worktree",
    "remediation-queue",
    "scan-state",
    "hidden-fees",
    "corpus-diff",
    # Added 2026-08-05 after a survey found this reader — the estate's ONE
    # component designed to answer "what is wrong here" — blind to both of its
    # live defect signals. Five Prometheus alerts had been firing for ten days
    # and three pulse jobs had failed, and neither appeared in `/weaknesses`
    # because every source above reads a FILE. They rank last on purpose: a
    # file-backed finding is reproducible from the repo, a live one is a
    # snapshot of this host at this second.
    "prometheus-alerts",
    "pulse-runs",
)

#: name -> required. A required source's absence is a defect; an optional
#: source's absence may just be a host that never installed the organ. Neither
#: is silence.
SOURCE_REQUIRED: dict[str, bool] = {
    "git-worktree": True,
    "remediation-queue": True,
    "scan-state": True,
    "hidden-fees": True,
    "corpus-diff": False,
    # Optional: a host without observability, or one whose Wing DB has not been
    # created yet, is not a defective host. Absence still speaks — it becomes an
    # `unavailable` report rather than nothing.
    "prometheus-alerts": False,
    "pulse-runs": False,
}


#: Sources whose freshness VALUE drives a severity somewhere in the estate.
#: `scan-state.last_full_scan` is read by the nightly drift watcher, so an
#: uncorroborated value there is not a documentation nit — it is the alarm
#: being fed by the thing it watches. Data, so a test can read it.
SOURCE_FRESHNESS_LOAD_BEARING: frozenset[str] = frozenset({"scan-state"})


def _freshness_weakness(report: SourceReport) -> Weakness | None:
    """A self-report contradicted by an independent signal, for ANY source.

    This is the general form of the `scan-state` scar. It lives here, once,
    rather than inside each source reader: the defect is not specific to
    `last_full_scan`, and the second place it appeared — `generated_at` in
    `remediation-queue.json`, measured byte-identical across a change that
    ADDED items — is a different file with the same shape.

    The disagreement is reported, never resolved. Preferring the claim
    re-creates the original defect; preferring the corroborator would hide a
    real run whose events never landed.
    """
    f = report.freshness
    if not f.self_reported or f.corroborated is not False:
        return None
    load_bearing = report.name in SOURCE_FRESHNESS_LOAD_BEARING
    return Weakness(
        weakness_id=f"freshness:{report.name}:not-corroborated",
        source=report.name,
        severity="high" if load_bearing else "medium",
        title=(
            f"{report.name}'s self-reported freshness is contradicted by "
            f"{f.corroborator}"
        ),
        derived_from_self_report=True,
        # The claim side of this disagreement came out of the source's file,
        # so it is committed exactly when that file is.
        evidence_committed=report.evidence_committed,
        evidence={
            "source": report.name,
            "path": report.path,
            "self_reported_value": f.value,
            "written_by": f.written_by,
            "corroborator": f.corroborator,
            "corroborator_value": f.corroborator_value,
        },
        observed={
            "skew_seconds": f.skew_seconds,
            "tolerance_seconds": CORROBORATION_TOLERANCE_S,
            "freshness_is_load_bearing": load_bearing,
            "consequence": (
                "a severity derived from this timestamp is derived from a claim "
                "the source makes about itself, and the claim does not hold"
            ) if load_bearing else (
                "the freshness field did not move with the content it describes"
            ),
        },
    )


def collect() -> list[SourceReport]:
    """Every source, in declared order. Never raises past a single source."""
    git_report, dirty = _source_git_worktree()
    file_sources: dict[str, Callable[[set[str]], SourceReport]] = {
        "remediation-queue": _source_remediation_queue,
        "scan-state": _source_scan_state,
        "hidden-fees": _source_hidden_fees,
        "corpus-diff": _source_corpus_diff,
        "prometheus-alerts": _source_prometheus_alerts,
        "pulse-runs": _source_pulse_runs,
    }
    reports = [git_report]
    for name in SOURCE_ORDER[1:]:
        fn = file_sources[name]
        try:
            reports.append(fn(dirty))
        except Exception as exc:  # noqa: BLE001 — one bad source must not blank the list
            reports.append(
                _unavailable(
                    name,
                    required=SOURCE_REQUIRED[name],
                    path=None,
                    status=STATUS_MALFORMED,
                    detail=f"reader raised {type(exc).__name__}: {exc}",
                )
            )

    # Cross-cutting, applied to every source uniformly: a self-report that its
    # own corroborator contradicts. One mechanism, not one patch per source.
    for report in reports:
        extra = _freshness_weakness(report)
        if extra is not None:
            report.weaknesses.append(extra)
    return reports


def rank(weaknesses: list[Weakness]) -> list[Weakness]:
    """Group by source (declared order), severity within, id as tie-break.

    Deterministic on purpose: two reads of an unchanged estate must produce the
    same list in the same order, or nothing downstream can diff them.
    """
    order = {name: i for i, name in enumerate(SOURCE_ORDER)}
    return sorted(
        weaknesses,
        key=lambda w: (
            order.get(w.source, len(order)),
            _SEV_RANK[w.severity],
            w.weakness_id,
        ),
    )


def read_weaknesses(
    *,
    top: int | None = None,
    sources: list[str] | None = None,
    min_severity: str | None = None,
) -> dict:
    """The whole reader. Filters narrow the OUTPUT; they never change a verdict.

    Note what the parameters can and cannot do: they select and truncate. There
    is no parameter that sets a severity, a title or an evidence field. Nothing
    a caller sends can make a weakness look better than the source says it is.
    """
    reports = collect()
    if sources:
        wanted = set(sources)
        unknown = wanted - set(SOURCE_ORDER)
        if unknown:
            raise HTTPException(
                status_code=400, detail=f"unknown source(s): {sorted(unknown)}"
            )
        reports = [r for r in reports if r.name in wanted]

    all_w = [w for r in reports for w in r.weaknesses]
    if min_severity:
        floor = normalize_severity(min_severity)
        if floor != str(min_severity).strip().lower():
            raise HTTPException(
                status_code=400,
                detail=f"unknown severity '{min_severity}'; use one of {list(SEVERITIES)}",
            )
        all_w = [w for w in all_w if _SEV_RANK[w.severity] <= _SEV_RANK[floor]]

    ranked = rank(all_w)
    total_before_top = len(ranked)
    if top is not None:
        ranked = ranked[:top]

    counts = {sev: 0 for sev in SEVERITIES}
    for w in all_w:
        counts[w.severity] += 1

    degraded = [r.name for r in reports if r.status != STATUS_OK]
    _, head_out = _git(repo_root(), "rev-parse", "HEAD")

    return {
        "read_at": _now().isoformat(),
        "repo_root": str(repo_root()),
        "head_sha": head_out.strip() or None,
        # False whenever ANY source failed to report. An empty `weaknesses` list
        # with `complete: false` means "nothing found AND the list is partial" —
        # the two must never collapse into "all clear".
        "complete": not degraded,
        "degraded_sources": degraded,
        "counts": {**counts, "total": total_before_top},
        "returned": len(ranked),
        "self_reported_sources": [
            r.name for r in reports if r.freshness.self_reported
        ],
        "sources": [r.to_dict() for r in reports],
        "weaknesses": [w.to_dict() for w in ranked],
    }


# ── Route ───────────────────────────────────────────────────────────────────


@router.get("/weaknesses")
async def get_weaknesses(
    top: int | None = Query(default=None, ge=1, le=500),
    source: list[str] | None = Query(default=None),
    min_severity: str | None = Query(default=None),
    _caller=Depends(require_loop_scope("read")),
):
    """Ranked weaknesses. Read-only, loopback-only, no body, no side effect."""
    return read_weaknesses(top=top, sources=source, min_severity=min_severity)
