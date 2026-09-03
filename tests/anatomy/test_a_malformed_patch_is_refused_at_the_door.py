"""A patch git cannot read is refused when it is offered, not a night later.

MEASURED 2026-08-31. The nightly loop produced exactly one model-authored
proposal — `rem:REM-156`, a nodered pin bump — and it was recorded at 01:33.
At 06:13, five hours later, every judge in its set refused it:

    diff does not apply at engine base: corrupt patch at <stdin>:5
    — the proposal was not judged; refusing to fall back to unpatched HEAD

Line 5 was the first CONTEXT line, and it had no leading space:

    @@ -19,7 +19,7 @@ nodered_timezone: "Europe/Prague"
    nodered_uid: 1000                     <- must be " nodered_uid: 1000"

The rest of the diff was correct: right file, right line, 4.0.9 -> 4.0.10. The
model had done the work and lost it to a format rule.

WHAT WAS ACTUALLY WRONG, AND IT IS NOT THE JUDGE. Refusing to judge unpatched
HEAD is exactly right and stays. The cost was WHERE the news arrived. The
proposer's AgentKit session had ended hours before the verdict existed, so the
one actor that could fix a malformed patch — the model that wrote it, still
holding the file it had just read — never heard. `record_proposal` checked that
the diff was non-empty, fingerprinted it, and measured it against the budget,
but never asked whether it was a readable patch.

So the check moved to the front door, where a refusal is a 409 the proposer
reads inside its own turn and can act on.

DELIBERATELY THE FORMAT, NOT THE APPLICATION. `git apply --check` answers "does
this apply at THIS base", which needs a sandbox and is the judge's question.
This asks only whether the bytes are a unified diff — context-free, no repo, no
worktree — which is the half that was failing.

Retro-verified 2026-08-31 against the live diff of proposal 23.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
LEDGER = REPO / "files/anatomy/bone/ledger.py"

#: VERIFIED WITH `git apply --check`, not by eye. The first version of this
#: fixture declared a 3-line hunk and supplied 2 body lines — git calls that
#: "corrupt patch" too, so the "well-formed" case in this file was malformed
#: from the day it was written and the check that later flagged it was right.
_GOOD = (
    "diff --git a/x b/x\n"
    "--- a/x\n"
    "+++ b/x\n"
    "@@ -1,3 +1,3 @@\n"
    " context\n"
    "-old\n"
    "+new\n"
    " tail\n"
)

#: The live shape, reduced: a hunk whose context line is flush left.
_LIVE_SHAPE = (
    "diff --git a/roles/pazny.nodered/defaults/main.yml b/roles/pazny.nodered/defaults/main.yml\n"
    "--- a/roles/pazny.nodered/defaults/main.yml\n"
    "+++ b/roles/pazny.nodered/defaults/main.yml\n"
    '@@ -19,7 +19,7 @@ nodered_timezone: "Europe/Prague"\n'
    "nodered_uid: 1000\n"
    '-nodered_version: "4.0.9"\n'
    '+nodered_version: "4.0.10"\n'
)


def _ledger():
    sys.path.insert(0, str(REPO / "files/anatomy/bone"))
    spec = importlib.util.spec_from_file_location("ledger", LEDGER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ledger"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_live_failure_is_caught_and_the_line_is_named() -> None:
    mod = _ledger()
    found = mod.malformed_hunk_line(_LIVE_SHAPE)
    assert found is not None, (
        "the diff that cost the loop its only proposal of the night is "
        "accepted — a context line with no leading space is what git calls a "
        "corrupt patch")
    line_no, text = found
    assert line_no == 5, f"named line {line_no}; git said 5, and the numbers must agree"
    assert "nodered_uid" in text, "the refusal does not quote the offending line"


#: The SECOND class, and the reason this file no longer models one spelling of
#: "malformed". rem:REM-212's diff had every body line correctly prefixed and a
#: header declaring seven lines over a six-line body — git: "corrupt patch at
#: <stdin>:10". It passed the first version of this check and was refused by
#: every judge in its set, hours later, exactly like the diff before it.
_MISCOUNTED = (
    "--- a/default.config.yml\n"
    "+++ b/default.config.yml\n"
    "@@ -1230,7 +1230,7 @@ install_portainer: true\n"
    " portainer_data_dir: x\n"
    " portainer_domain: y\n"
    " portainer_port: 9002\n"
    '-portainer_version: "2.44.0"\n'
    '+portainer_version: "2.45.0"\n'
    " portainer_admin_password: z\n"
    " portainer_admin_auto_reset: false\n"
)


def test_a_hunk_that_miscounts_its_own_lines_is_caught() -> None:
    """The class the first draft missed, taken from the live proposal."""
    mod = _ledger()
    found = mod.malformed_hunk_line(_MISCOUNTED)
    assert found is not None, (
        "a hunk header declaring 7 lines over a 6-line body is accepted; git "
        "calls it corrupt and the judge refuses it hours later")
    line_no, why = found
    assert line_no == 3, f"named line {line_no}; the header is on line 3"
    assert "declares 7 old and 7 new" in why and "supplies 6 and 6" in why, (
        f"the refusal does not say what to recount: {why!r}")


def test_a_well_formed_patch_passes() -> None:
    """The half that matters more: a check that refuses everything would stop
    the loop entirely, which is a worse failure than the one it fixes."""
    mod = _ledger()
    assert mod.malformed_hunk_line(_GOOD) is None
    # Several files, and the no-newline marker git itself emits.
    multi = _GOOD + _GOOD.replace("a/x b/x", "a/y b/y").replace("a/x", "a/y").replace("b/x", "b/y")
    assert mod.malformed_hunk_line(multi) is None
    # A header with no counts at all means 1 and 1, and is legal.
    assert mod.malformed_hunk_line(
        "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n") is None
    # An addition that grows the file: 2 old, 3 new.
    assert mod.malformed_hunk_line(
        "--- a/x\n+++ b/x\n@@ -1,2 +1,3 @@\n ctx\n+added\n ctx2\n") is None
    assert mod.malformed_hunk_line(_GOOD + "\\ No newline at end of file\n") is None


def test_the_boundary_with_git_is_where_it_was_drawn() -> None:
    """CROSS-CHECKED AGAINST REAL GIT, 2026-08-31, because a hand-written diff
    parser that disagrees with git is worse than none.

    Every fixture in this file was run through `git apply --check` in a scratch
    repository. On FORMAT the two agree exactly — flush-left context and a
    miscounted hunk are "corrupt patch" to both. They part on APPLICABILITY:
    git also rejects a well-formed patch whose context does not match the file
    ("patch does not apply"), and this check accepts it on purpose, because
    that question belongs to the judge, at a base, in a sandbox.

    The distinction is legible in git's own two error strings, and the split
    means a proposal is never refused here for a reason the front door cannot
    honestly know.
    """
    mod = _ledger()
    # Well-formed but would not apply anywhere: accepted here, judged later.
    assert mod.malformed_hunk_line(
        "--- a/nowhere\n+++ b/nowhere\n@@ -1,2 +1,2 @@\n who\n-knows\n+what\n") is None


def test_the_refusal_reaches_record_proposal_as_a_stable_code() -> None:
    """`ProposalRefused.reason` is a machine code by contract, never free text —
    the runner and the skill both branch on it."""
    src = LEDGER.read_text(encoding="utf-8")
    body = src.split("def record_proposal")[1].split("def ")[0]
    assert '"malformed-diff"' in body, (
        "record_proposal does not refuse a malformed diff, so it is recorded "
        "and discovered by a judge hours later, after the session that could "
        "have fixed it has ended")
    assert "malformed-diff      —" in src, (
        "the new refusal code is not documented beside the others in "
        "ProposalRefused's docstring, where every consumer looks it up")


def test_the_check_runs_before_the_row_is_written() -> None:
    """Order matters: refusing AFTER the insert would burn an attempt against
    the retry ceiling for a patch that was never judgeable."""
    src = LEDGER.read_text(encoding="utf-8")
    body = src.split("def record_proposal")[1].split("def ")[0]
    assert body.index("malformed-diff") < body.index("INSERT INTO loop_proposals"), (
        "the malformed-diff refusal happens after the proposal is written")


#: THE THIRD CLASS (rem:REM-244, proposal 5dbfc03e, 2026-09-02 — filed the day
#: after the first two classes shipped): every prefix correct, every count
#: correct, and no newline after the final hunk line. `split("\n")` hands the
#: tail over as an ordinary element so both earlier checks pass; git says
#: "corrupt patch at <stdin>:5". Measured 2026-09-03 against the live row
#: (last byte != \n) and minimally with `git apply --check`.
_UNTERMINATED = (
    "--- a/default.config.yml\n"
    "+++ b/default.config.yml\n"
    "@@ -1 +1 @@\n"
    '-gitea_version: "1.27.2"\n'
    '+gitea_version: "1.27.3"'
)


def test_an_unterminated_final_line_is_caught() -> None:
    mod = _ledger()
    found = mod.malformed_hunk_line(_UNTERMINATED)
    assert found is not None, (
        "a diff whose final hunk line has no trailing newline is accepted; "
        "git calls it corrupt and the judge refuses it hours later — the "
        "REM-244 shape, one proposal after the front-door check shipped")
    line_no, why = found
    assert line_no == 5, f"named line {line_no}; git said 5"
    assert "newline" in why, f"the refusal does not name the missing newline: {why!r}"


def test_an_unterminated_no_newline_marker_is_legal() -> None:
    """The exemption, measured: git reads an unterminated '\\ No newline at
    end of file' marker fine (rc 1, not 128). Refusing it would block the one
    diff shape git itself emits without a trailing newline."""
    mod = _ledger()
    marker_tail = (
        "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
        "\\ No newline at end of file"
    )
    assert mod.malformed_hunk_line(marker_tail) is None
