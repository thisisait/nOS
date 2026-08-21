"""A green verdict nobody can see is indistinguishable from no verdict at all.

THE MEASUREMENT THAT PROMPTED THIS (2026-08-19). Two proposals passed every
judge on 2026-08-16 — `rem:REM-204` (wordpress 7.0.2 → 7.0.4) and `rem:REM-159`
(gitlab 18.11.7 → 18.11.9), both with real diffs, both sealed into the WORM
chain by an identity the proposer could not touch. Three days later:

    default.config.yml:1357  wordpress_version: "7.0.2"
    default.config.yml:1692  gitlab_version:    "18.11.7-ce.0"
    remediation-queue.json   REM-204: pending · REM-159: pending

Nothing had applied them, which is CORRECT — docs/idea/11-agentic-loop-contract.md
§7 non-goal 5 says application is an operator act or a forge MR and nothing
merges on a green verdict. What was wrong is that nothing SAID so. `tools/loop-status.py` reported
"2p/0f/1i" and `tools/red-status.py` listed three reds, none of them this. The
loop's most expensive output — a patch five judges blessed — had no surface, so
it decayed in silence. That is `docs/hidden_fees/08` one storey up: absence
reading as success.

AND IT DID DECAY. Both verdicts were sealed against a tree whose
`default.config.yml` has since moved. Applying either patch to HEAD today would
be an act no judge has ruled on. A reader that answered the easy question ("does
the patch still apply?") and skipped the hard one ("to the tree that was
judged?") would have called both ready and handed back the claim the ledger
exists to replace.

WHAT THIS FILE PINS

  1. The state comes from git, forward AND reversed. One probe cannot tell a
     landed patch from one that never fit — `git apply --check` returning
     non-zero means both. Every state below is exercised against a real
     temporary repository, so this gate cannot be satisfied by editing it.
  2. `landed` is never the answer to a question that could not be asked. An
     absent or broken git yields `unknown`, the same discipline
     `tools/red-status.py` applies to an unreadable source.
  3. A patch git cannot PARSE is its own state. Measured: proposal `074dec8a`
     carries a corrupt hunk the ledger accepted. It drew `indeterminate` from
     the judges, correctly, and a reader that only asked "does it apply?" would
     have filed it beside the merely-stale ones and sent someone to rebase it.
  4. A passed verdict that has not landed reaches `red-status`. The reader
     existing is not the same as the operator seeing it; the 2026-08-18 lesson
     was that a state nobody asks for is a state nobody has.
  5. The reader cannot write. It opens the ledger read-only and contains no
     INSERT/UPDATE/DELETE — `open_ledger(role)` splits those verbs across
     capabilities on purpose, and a reporter that could also seal would collapse
     the split its own report depends on.

CI-safe: a scratch git repo under tmp_path and pure source reading. No wing.db,
no network, no live estate — every ledger-shaped input here is a fixture.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LOOP_STATUS = REPO / "tools" / "loop-status.py"
RED_STATUS = REPO / "tools" / "red-status.py"


def _load(path: Path, name: str):
    """Import a hyphenated tool by path — these are commands, not modules."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def loop():
    return _load(LOOP_STATUS, "_loop_status_gate")


@pytest.fixture
def scratch(tmp_path, monkeypatch, loop):
    """A real git repo with one committed file, and the reader pointed at it.

    Pointing `REPO` at the scratch tree is what makes the state table below a
    measurement rather than an assertion about strings: every verdict here is
    git's, produced by the same call the tool makes in production.
    """
    def git(*argv, **kw):
        return subprocess.run(["git", *argv], cwd=tmp_path, text=True,
                              capture_output=True, check=False, **kw)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "gate@example.invalid")
    git("config", "user.name", "gate")
    target = tmp_path / "conf.yml"
    target.write_text("alpha: 1\nversion: \"1.0.0\"\nomega: 9\n", encoding="utf-8")
    git("add", "conf.yml")
    git("commit", "-qm", "base")
    monkeypatch.setattr(loop, "REPO", tmp_path)
    return tmp_path, git, target


#: A patch that bumps the committed version — the shape every real proposal so
#: far has had (`intent_class: version-pin-bump`).
BUMP = """--- a/conf.yml
+++ b/conf.yml
@@ -1,3 +1,3 @@
 alpha: 1
-version: "1.0.0"
+version: "1.0.1"
 omega: 9
"""


def test_the_tool_and_its_flag_exist():
    """Positive control: everything below reads one of these two files."""
    assert LOOP_STATUS.is_file() and RED_STATUS.is_file()
    src = LOOP_STATUS.read_text(encoding="utf-8")
    assert '"--awaiting"' in src, (
        "the --awaiting flag is gone; the exit half of the loop has no surface "
        "again and a passed verdict decays unseen"
    )


def test_a_patch_that_is_not_in_the_tree_reads_as_applies(scratch, loop):
    state, _ = loop._apply_state(BUMP)
    assert state == "applies", (
        "a patch that fits the tree and is not in it must be reported as "
        "applicable; this is the state the operator acts on"
    )


def test_a_patch_already_in_the_tree_reads_as_landed(scratch, loop):
    """The reverse probe is the whole reason there are two.

    Without it, an applied patch and a patch that never fitted both come back
    non-zero from `git apply --check`, and the reader would report the loop's
    one success as a conflict.
    """
    tmp, git, target = scratch
    target.write_text("alpha: 1\nversion: \"1.0.1\"\nomega: 9\n", encoding="utf-8")
    git("commit", "-qam", "landed")
    state, _ = loop._apply_state(BUMP)
    assert state == "landed", (
        "an applied patch reports as %r — the reversed probe is gone, so the "
        "loop's successes are indistinguishable from its conflicts" % state
    )


def test_a_tree_that_moved_under_the_patch_reads_as_conflict(scratch, loop):
    tmp, git, target = scratch
    target.write_text("alpha: 1\nversion: \"2.0.0\"\nomega: 9\n", encoding="utf-8")
    git("commit", "-qam", "moved")
    state, detail = loop._apply_state(BUMP)
    assert state == "conflict", f"expected conflict, got {state!r} ({detail})"


def test_a_patch_git_cannot_parse_is_its_own_state(scratch, loop):
    """Measured on proposal 074dec8a — a corrupt hunk the ledger accepted.

    Folding this into `conflict` sends someone to rebase a patch that was never
    well-formed. The owner of a malformed patch is the proposer, not the tree.
    """
    corrupt = BUMP.replace("@@ -1,3 +1,3 @@", "@@ -1,7 +1,7 @@")
    state, detail = loop._apply_state(corrupt)
    assert state == "unusable", (
        f"a patch git refuses to parse reports as {state!r}; the corrupt-hunk "
        f"case then reads as a stale one and gets rebased instead of rewritten"
    )
    assert detail, "the unusable state must carry git's reason, not just a label"


def test_git_being_unaskable_yields_unknown_and_never_landed(scratch, loop, monkeypatch):
    """`landed` must never be the fallback for a question that failed to run.

    This is the estate's oldest defect in miniature (`docs/hidden_fees/08`): an
    absent answer read as a good one. Simulated the only way that keeps the test
    hermetic — the OSError branch `_git` already funnels every exec failure into.
    """
    monkeypatch.setattr(loop.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no git")))
    state, detail = loop._apply_state(BUMP)
    assert state == "unknown", (
        f"a reader that cannot run git reported {state!r}; absence must be "
        f"UNKNOWN, never a verdict about the tree"
    )
    assert "OSError" in detail


def test_staleness_is_measured_from_the_verdict_tree_not_the_proposal(scratch, loop):
    """Two columns are called `tree_sha` and they hold different object kinds.

    `loop_proposals.tree_sha` is the COMMIT the proposer had checked out;
    `loop_verdicts.tree_sha` is the git TREE the judges actually ruled on
    (HEAD-plus-the-patch, built in a sandbox). The first version of this reader
    measured from the proposal, so a proposal stayed "decayed" forever however
    recently it had been re-judged — the proposal's sha never changes. Caught
    2026-08-19 by re-judging one and watching it stay red.

    The operative question is whether the judges' BASE is still HEAD, so every
    path differing from HEAD other than the patched ones is drift.
    """
    tmp, git, target = scratch
    tree_now = git("rev-parse", "HEAD^{tree}").stdout.strip()

    moved, err = loop._base_moved_since(tree_now, ["conf.yml"])
    assert (moved, err) == ([], None), "an unmoved base must report no drift"

    (tmp / "unrelated.txt").write_text("something else entirely\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "the base moves under the judges")
    moved, err = loop._base_moved_since(tree_now, ["conf.yml"])
    assert err is None and moved == ["unrelated.txt"], (
        f"drift outside the target paths must be named, got {moved!r}/{err!r}; "
        f"without it a verdict silently transfers to a tree no judge saw"
    )


def test_a_change_to_the_target_path_alone_is_not_drift(scratch, loop):
    """The verdict tree IS base+patch, so the patched path always differs.

    Counting it as drift would make every fresh verdict read as decayed — the
    mirror image of the bug above, and just as effective at stopping the loop.
    """
    tmp, git, target = scratch
    tree_now = git("rev-parse", "HEAD^{tree}").stdout.strip()
    target.write_text("alpha: 1\nversion: \"9.9.9\"\nomega: 9\n", encoding="utf-8")
    git("commit", "-qam", "the patched path differs, as it must")
    moved, err = loop._base_moved_since(tree_now, ["conf.yml"])
    assert err is None and moved == [], (
        f"the target path was counted as drift ({moved!r}); every verdict would "
        f"then be born stale"
    )


def test_an_unknown_judged_tree_is_an_inability_to_ask(scratch, loop):
    """Not 'no drift'. A tree this clone does not have is a question that failed.

    A shallow clone or a pruned object would otherwise turn every stale verdict
    fresh — the failure mode is silent and points the wrong way.
    """
    moved, err = loop._base_moved_since("0" * 40, ["conf.yml"])
    assert moved == [] and err and "not in this clone" in err


def test_red_status_surfaces_an_unlanded_verdict():
    """A reader nobody reads is the state this estate keeps paying for."""
    red = _load(RED_STATUS, "_red_status_gate")
    lines = red.reds({
        "loop_verdicts": {"unlanded": [
            {"weakness_id": "rem:REM-204", "state": "re-judge",
             "uuid": "6f139e22", "verdict_at": "2026-08-16 18:54:18"},
        ]},
    })
    assert any("REM-204" in ln for ln in lines), (
        "a passed proposal that never reached the tree does not appear in "
        "red-status; it is then visible only to whoever thinks to run "
        "loop-status --awaiting, which is how the first three days were lost"
    )


def test_red_status_reports_an_unreadable_loop_as_unknown_not_green():
    """The source list, not the red list, is where a failed read must land."""
    red = _load(RED_STATUS, "_red_status_gate2")
    src = RED_STATUS.read_text(encoding="utf-8")
    assert "loop_verdicts" in src and "stalled_verdicts" in src
    # None from the reader → the collect() loop files it under sources_missing,
    # which reds() renders as an explicit UNKNOWN line.
    lines = red.reds({"sources_missing": ["/nowhere/loop-status.py"]})
    assert any("UNKNOWN" in ln for ln in lines), (
        "an unreadable loop reader is being treated as no news; every other "
        "source in this file reports absence as UNKNOWN"
    )


def test_the_reader_cannot_write_to_the_ledger():
    """Constraint A survives only while the reporter has no write verbs."""
    src = LOOP_STATUS.read_text(encoding="utf-8")
    assert "mode=ro" in src, "the ledger is no longer opened read-only"
    tree = ast.parse(src)
    sql = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    forbidden = ("insert into", "update ", "delete from", "drop ")
    offenders = [
        s.strip()[:60] for s in sql
        if any(verb in s.lower() for verb in forbidden)
    ]
    assert not offenders, (
        f"the loop reporter contains write SQL {offenders}; propose, judge and "
        f"seal live on separate capabilities and a reporter holds none of them"
    )


def test_a_proposal_nobody_has_judged_is_reported(loop, tmp_path, monkeypatch):
    """The gap the first unattended night fell into.

    `loop:propose` filed a proposal at 01:38 on 2026-08-21; `loop:drive` at
    06:12 said "no passed proposal is waiting to land". Both were telling the
    truth: this reader selected only `pass` rows, so a fresh proposal was
    invisible between the step that makes one and the step that acts on one.
    During the attended days a human judged each proposal within a minute of
    filing it and bridged the gap by hand.
    """
    import sqlite3

    db = tmp_path / "wing.db"
    with sqlite3.connect(db) as seed:
        seed.execute("CREATE TABLE loop_proposals (id INTEGER PRIMARY KEY, uuid TEXT, "
                     "fingerprint TEXT, weakness_id TEXT, intent_class TEXT, "
                     "target_paths TEXT, diff_text TEXT, proposer_id TEXT, created_at TEXT)")
        seed.execute("CREATE TABLE loop_verdicts (id INTEGER PRIMARY KEY, "
                     "proposal_id INTEGER, result TEXT, created_at TEXT, tree_sha TEXT)")
        seed.execute("INSERT INTO loop_proposals VALUES (1,'aaaa1111','fp','fee:99',"
                     "'wiring-fix','[\"x\"]',?, 'agent:x','2026-08-21 01:38')", (BUMP,))
        # a second, already-passed proposal so the split header has both kinds
        seed.execute("INSERT INTO loop_proposals VALUES (2,'bbbb2222','fp2','fee:98',"
                     "'wiring-fix','[\"x\"]',?, 'agent:x','2026-08-20 01:00')", (BUMP,))
        seed.execute("INSERT INTO loop_verdicts VALUES (1,2,'pass','2026-08-20 02:00','deadbeef')")
    monkeypatch.setattr(loop, "WING_DB", db)

    report = loop.awaiting()
    by_uuid = {r["uuid"]: r for r in report["rows"]}
    assert "aaaa1111" in by_uuid, (
        "a proposal with no verdict is absent from the report; nothing "
        "downstream can act on what nothing reports"
    )
    assert by_uuid["aaaa1111"]["state"] == "unjudged", (
        f"an unruled proposal reported as {by_uuid['aaaa1111']['state']!r} — it "
        f"is neither a pass nor a failure and must not be filed as either"
    )
    assert any(r["state"] == "unjudged" for r in report["unlanded"]), (
        "an unjudged proposal is not counted among the unlanded, so red-status "
        "stays quiet about a loop that has stopped moving"
    )


def test_a_failed_proposal_is_still_not_listed(loop, tmp_path, monkeypatch):
    """Widening to unjudged must not widen to REFUSED.

    A judge said no. Listing it would invite the driver to retry a question
    already answered, which is what the attempt ceiling exists to stop.
    """
    import sqlite3

    db = tmp_path / "wing.db"
    with sqlite3.connect(db) as seed:
        seed.execute("CREATE TABLE loop_proposals (id INTEGER PRIMARY KEY, uuid TEXT, "
                     "fingerprint TEXT, weakness_id TEXT, intent_class TEXT, "
                     "target_paths TEXT, diff_text TEXT, proposer_id TEXT, created_at TEXT)")
        seed.execute("CREATE TABLE loop_verdicts (id INTEGER PRIMARY KEY, "
                     "proposal_id INTEGER, result TEXT, created_at TEXT, tree_sha TEXT)")
        seed.execute("INSERT INTO loop_proposals VALUES (1,'cccc3333','fp','fee:97',"
                     "'wiring-fix','[\"x\"]',?, 'agent:x','2026-08-21 01:38')", (BUMP,))
        seed.execute("INSERT INTO loop_verdicts VALUES (1,1,'fail','2026-08-21 02:00','deadbeef')")
    monkeypatch.setattr(loop, "WING_DB", db)

    assert [r["uuid"] for r in loop.awaiting()["rows"]] == [], (
        "a proposal the judges REFUSED is listed as actionable"
    )

