"""An indeterminate verdict must be reachable — and its re-judging bounded.

THE MEASUREMENT (2026-08-25, verified twice). `tools/loop-status.py::awaiting()`
selected `WHERE v.result = 'pass' OR v.id IS NULL`, so a proposal whose LATEST
verdict was `indeterminate` vanished from the only list the driver reads, and
`tools/loop-pr.py --rejudge` — which walks rows awaiting() returned — could
never re-judge it. An indeterminate was a ONE-WAY DOOR, and that door was
walked through by accident: `state/judge-sets.yml` carried `min_work: 4060`
arrived at by arithmetic (operator collection 4085 minus an assumed −22 gap)
where the judge env measures 4032, and proposals 18/19/20 drew

    "exit says pass but tests_executed=4032 < min_work=4060 — scope shrank"

at 06:17:30 / 06:23:45 / 06:30:06 — verdicts about the constant, not the
proposals. Correcting the floor (f3f7a39b) could not bring them back.

WHAT THIS FILE PINS

  1. REACHABILITY. A proposal whose latest verdict is `indeterminate` appears
     in awaiting() as its OWN state — never folded into `re-judge` or `ready`,
     never mistaken for `unjudged` ("no judge has ruled" and "a judge declined
     to answer" are different facts) — and the driver's row filter includes it,
     gated behind --rejudge exactly like a decayed verdict. It is NEVER treated
     as a pass: the only act is a fresh judge run.

  2. THE BOUND. Without one, a proposal ambiguous BY ITS NATURE burns a judge
     run every night forever. The bound is tree identity, not a retry count:
     `loop_verdicts.tree_sha` is the exact tree the judges ran on (base +
     patch), so when nothing outside the patch's own paths differs between it
     and HEAD, a fresh run's inputs are byte-identical and the row is
     `indeterminate-held` — out of the driver's reach, with a detail that names
     the unblocking condition (a commit that moves the base). The morning above
     unblocks itself under this rule: the min_work fix was a commit to
     state/judge-sets.yml, which is in the tree.

  3. The renderer knows both states (`_STATE_ORDER` + `STATE_GLOSS`) — a state
     string the renderer does not know is how these tables grow holes — and a
     `fail` row stays excluded: a judge ANSWERED.

CI-safe: a throwaway sqlite ledger + monkeypatched git probes. No live estate,
no network, nothing written outside tmp_path.
"""

from __future__ import annotations

import ast
import importlib.util
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def loop_status():
    return _load(REPO / "tools" / "loop-status.py", "_loop_status_gate")


@pytest.fixture()
def loop_pr():
    return _load(REPO / "tools" / "loop-pr.py", "_loop_pr_gate")


MOVED_TREE = "aaaa1111" * 5   # base moved since the verdict
SAME_TREE = "bbbb2222" * 5    # provably nothing but the patch differs


@pytest.fixture()
def ledger(tmp_path: Path) -> Path:
    """Four proposals: indeterminate-on-a-moved-tree, indeterminate-on-an-
    unchanged-tree, failed, and indeterminate-then-passed (latest wins)."""
    db = tmp_path / "wing.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE loop_proposals (
            id INTEGER PRIMARY KEY, uuid TEXT, weakness_id TEXT,
            intent_class TEXT, gate_set TEXT, target_paths TEXT,
            tree_sha TEXT, proposer_id TEXT, diff_text TEXT,
            created_at TEXT
        );
        CREATE TABLE loop_verdicts (
            id INTEGER PRIMARY KEY, proposal_id INTEGER, result TEXT,
            tree_sha TEXT, prev_hash TEXT, created_at TEXT
        );
        """
    )
    diff = "--- a/default.config.yml\n+++ b/default.config.yml\n@@\n-x\n+y\n"
    rows = [
        (1, "u-moved-11", "rem:T-MOVED", MOVED_TREE),
        (2, "u-same-222", "rem:T-SAME", SAME_TREE),
        (3, "u-fail-333", "rem:T-FAIL", MOVED_TREE),
        (4, "u-pass-444", "rem:T-PASS", MOVED_TREE),
    ]
    for pid, uuid, wid, _tree in rows:
        conn.execute(
            "INSERT INTO loop_proposals VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, uuid, wid, "version-pin-bump", "repo",
             '["default.config.yml"]', "c0ffee", "agent:test", diff,
             f"2026-08-25 06:0{pid}:00"),
        )
    verdicts = [
        (1, 1, "indeterminate", MOVED_TREE),
        (2, 2, "indeterminate", SAME_TREE),
        (3, 3, "fail", MOVED_TREE),
        (4, 4, "indeterminate", MOVED_TREE),   # superseded …
        (5, 4, "pass", SAME_TREE),             # … the LATEST verdict rules
    ]
    for vid, pid, result, tree in verdicts:
        conn.execute(
            "INSERT INTO loop_verdicts VALUES (?,?,?,?,?,?)",
            (vid, pid, result, tree, None, f"2026-08-25 06:1{vid}:00"),
        )
    conn.commit()
    conn.close()
    return db


@pytest.fixture()
def report(loop_status, ledger, monkeypatch):
    """awaiting() against the throwaway ledger, git probes stubbed.

    `_base_moved_since` is answered by the verdict tree the row carries, which
    is exactly the contract the real one honors: MOVED_TREE differs from HEAD
    beyond the patch, SAME_TREE does not.
    """
    monkeypatch.setattr(loop_status, "WING_DB", ledger)
    monkeypatch.setattr(loop_status, "_apply_state", lambda _d: ("applies", ""))
    monkeypatch.setattr(
        loop_status, "_base_moved_since",
        lambda tree, _paths: ([], None) if tree == SAME_TREE
        else (["state/judge-sets.yml"], None))
    monkeypatch.setattr(loop_status, "_dirty", lambda _p: [])
    monkeypatch.setattr(loop_status, "_git", lambda *a, **k: (0, ""))
    monkeypatch.setattr(loop_status, "_git_head", lambda: "deadbeef" * 5)
    return loop_status.awaiting()


def _by_wid(report: dict) -> dict:
    return {r["weakness_id"]: r for r in report["rows"]}


def test_an_indeterminate_on_a_moved_tree_is_its_own_state(report):
    row = _by_wid(report)["rem:T-MOVED"]
    assert row["state"] == "indeterminate", (
        "a proposal whose latest verdict is indeterminate and whose judged "
        "tree has moved must surface as `indeterminate` — the one-way door "
        "of 2026-08-25 (proposals 18/19/20)")
    assert row["verdict"] == "indeterminate"
    # And it is on the driver's list.
    assert row["uuid"] in {r["uuid"] for r in report["unlanded"]}


def test_the_bound_holds_an_unchanged_tree(report):
    row = _by_wid(report)["rem:T-SAME"]
    assert row["state"] == "indeterminate-held", (
        "re-judging a tree whose every input is identical to the run that "
        "declined is provably pointless — the row must be held, not queued")
    # The refusal says WHY and names what unblocks it.
    assert "cannot answer differently" in row["detail"]
    assert "commit" in row["detail"], (
        "the detail must name the unblocking condition — a commit that "
        "moves the base")
    # Held is nobody's act tonight: not on the driver's list.
    assert row["uuid"] not in {r["uuid"] for r in report["unlanded"]}


def test_a_failed_proposal_stays_off_the_desk(report):
    assert "rem:T-FAIL" not in _by_wid(report), (
        "a judge ANSWERED — a failed proposal is not an item on anybody's "
        "desk and must stay unlisted")


def test_the_latest_verdict_rules(report):
    row = _by_wid(report)["rem:T-PASS"]
    assert row["state"] == "ready", (
        "an indeterminate superseded by a pass is a pass — only the LATEST "
        "verdict decides the state")


def test_the_renderer_knows_both_states(loop_status):
    for state in ("indeterminate", "indeterminate-held"):
        assert state in loop_status._STATE_ORDER, (
            f"{state} missing from _STATE_ORDER — a state the renderer does "
            f"not know is how these tables grow holes")
        assert state in loop_status.STATE_GLOSS, (
            f"{state} missing from STATE_GLOSS")


def _driver_row(state: str) -> dict:
    return {
        "uuid": "u-moved-11", "weakness_id": "rem:T-MOVED", "state": state,
        "intent_class": "version-pin-bump", "proposer_id": "agent:test",
        "target_paths": ["default.config.yml"], "_diff": "+x\n",
    }


def test_the_driver_rejudges_an_indeterminate(loop_pr, monkeypatch):
    """land() reaches _rejudge for state `indeterminate`, and a non-pass
    result never proceeds toward the forges."""
    calls: list[tuple] = []
    logs: list[str] = []
    monkeypatch.setattr(
        loop_pr, "_rejudge",
        lambda uuid, gs, t: (calls.append((uuid, gs)) or
                             ("indeterminate", "still ambiguous")))
    monkeypatch.setattr(
        loop_pr, "_forge",
        lambda name: (_ for _ in ()).throw(
            AssertionError("a non-pass re-judge must never reach a forge")))
    rc = loop_pr.land(_driver_row("indeterminate"), base="dev",
                      gate_set="repo", rejudge=True, timeout=5, act=True,
                      log=logs.append)
    assert rc == 0
    assert calls == [("u-moved-11", "repo")], (
        "the driver must call _rejudge for an indeterminate — reachability "
        "is the whole fix")
    assert any("nothing landed" in line for line in logs)


def test_the_driver_gates_it_behind_rejudge(loop_pr, monkeypatch):
    monkeypatch.setattr(
        loop_pr, "_rejudge",
        lambda *_a: (_ for _ in ()).throw(
            AssertionError("without --rejudge no judge run may fire")))
    logs: list[str] = []
    rc = loop_pr.land(_driver_row("indeterminate"), base="dev",
                      gate_set="repo", rejudge=False, timeout=5, act=True,
                      log=logs.append)
    assert rc == 0
    assert any("--rejudge" in line for line in logs)


def _main_state_filter() -> list[str]:
    """The tuple main() filters awaiting() rows by — read from the AST, not a
    regex, so a docstring mentioning a state cannot satisfy this."""
    tree = ast.parse((REPO / "tools" / "loop-pr.py").read_text("utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Compare)
                and any(isinstance(op, ast.In) for op in node.ops)
                and isinstance(node.comparators[0], ast.Tuple)):
            values = [c.value for c in node.comparators[0].elts
                      if isinstance(c, ast.Constant)]
            if "unjudged" in values and "ready" in values:
                return values
    pytest.fail("could not find main()'s state filter in tools/loop-pr.py")


def test_the_drivers_filter_reaches_it_and_respects_the_bound():
    values = _main_state_filter()
    assert "indeterminate" in values, (
        "main() must hand indeterminate rows to land() — otherwise the state "
        "exists and nothing walks it: the one-way door with a fresh label")
    assert "indeterminate-held" not in values, (
        "a held row is the BOUND — the reader proved a fresh run would see "
        "byte-identical inputs; the driver must not burn a judge run on it")
