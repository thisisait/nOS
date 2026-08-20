"""A FAIL you cannot diagnose is a claim with a number attached.

THE MEASUREMENT (2026-08-20). The loop's entry half ran attended for the first
time. It produced a real patch against `rem:REM-191`, the judges sealed FAIL,
and the reason read:

    pytest-anatomy   fail   exit=1   work=14890/3690
    reason: 18 failing test(s)

`stdout_head` held 2000 characters of pytest progress dots. Not one of the 18
names. The verdict was true and unactionable, and a faithful replay in a clean
worktree — control run and patched run, same tree, vendor present — came back
`3795 passed, 0 failed` both times, so the FAIL could not even be reproduced.

WHY IT HAPPENED, AND IT IS THE INTERESTING PART. Both halves of the mechanism
were already correct and they cancelled:

  * `ledger._stdout_excerpt` keeps BOTH ENDS, and its docstring says so — "with
    the middle named rather than dropped".
  * `judges.py` handed it `done.output[:2000]`.

Two layers, each doing half the job, the outer one discarding exactly what the
inner one existed to preserve. Nothing was broken; nothing was tested end to
end either, and pytest is the one judge whose verdict lives at the TAIL.
`.woodpecker/tests.yml` had already written the lesson down in a comment
("-rA … so even a truncated CI log still reports the critical info"). The engine
had not read it.

WHAT THIS FILE PINS. Not the character budgets — those may move. It pins the
property the budgets exist for: **a judge's recorded excerpt must still contain
the end of its output**, through the whole chain, for output shaped like the
one that actually broke.

CI-safe: pure functions and synthetic text. No ledger, no sandbox, no network.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"


def _load(name: str):
    """Import a Bone module the way Bone does — on sys.path, not by file path.

    `spec_from_file_location` gives these modules no package context and their
    module-level dataclasses fail to resolve their own forward references.
    """
    import sys

    if str(BONE) not in sys.path:
        sys.path.insert(0, str(BONE))
    return importlib.import_module(name)


#: Shaped like the run that broke: a long progress body, the verdict at the end.
def _pytest_output(failures: int = 18, dots: int = 9000) -> str:
    body = "\n".join("." * 72 + f" [{i:>3}%]" for i in range(dots // 72))
    names = "\n".join(
        f"FAILED tests/anatomy/test_thing_{i}.py::test_case_{i} - AssertionError"
        for i in range(failures)
    )
    return (
        "============================= test session starts ==============================\n"
        + body
        + "\n=========================== short test summary info ============================\n"
        + names
        + f"\n{failures} failed, 3780 passed, 39 skipped in 265.11s\n"
    )


def test_both_helpers_exist():
    """Positive control: the two ends of the chain this file is about."""
    assert hasattr(_load("judges"), "_capture_excerpt")
    assert hasattr(_load("ledger"), "_stdout_excerpt")


def test_the_capture_keeps_the_end_of_the_output():
    judges = _load("judges")
    kept = judges._capture_excerpt(_pytest_output())
    assert "short test summary info" in kept, (
        "the judge's capture dropped pytest's summary header — the verdict is "
        "recorded without the only lines that say what failed"
    )
    assert "18 failed" in kept


def test_the_whole_chain_preserves_the_failing_names():
    """capture → ledger excerpt, exactly as a sealed row is written.

    This is the assertion that would have failed on 2026-08-20 and the reason
    the file exists: each helper passed its own unit test while the composition
    threw the answer away.
    """
    judges, ledger = _load("judges"), _load("ledger")
    stored = ledger._stdout_excerpt(judges._capture_excerpt(_pytest_output()))
    found = re.findall(r"FAILED (\S+)", stored)
    assert found, (
        "no FAILED line survived capture → ledger. A reader of this row learns "
        "that N tests failed and can never learn which — which is what "
        "'18 failing test(s)' with 2000 characters of dots actually was."
    )


def test_the_middle_is_named_not_silently_dropped():
    """Elision must announce itself; a silent cut reads as complete output."""
    judges = _load("judges")
    kept = judges._capture_excerpt(_pytest_output(dots=200_000))
    assert "elided" in kept, (
        "output was truncated with no marker — a reader cannot tell a complete "
        "capture from a cut one"
    )


def test_short_output_is_untouched():
    judges = _load("judges")
    short = "one line of output\n"
    assert judges._capture_excerpt(short) == short


@pytest.mark.parametrize("module", ["judges", "ledger"])
def test_neither_helper_is_a_bare_head_slice(module):
    """The defect in source form, on both sides.

    A bare `text[:N]` return is exactly what `judges.py` did, and it is what a
    future simplification would reach for.
    """
    src = (BONE / f"{module}.py").read_text(encoding="utf-8")
    fn = "_capture_excerpt" if module == "judges" else "_stdout_excerpt"
    start = src.index(f"def {fn}(")
    body = src[start:start + 1400]
    assert "[-" in body, (
        f"{module}.{fn} never indexes from the END of the string, so it cannot "
        f"be keeping a tail"
    )


def test_the_capture_site_does_not_re_truncate():
    """The call site, not just the helper.

    Restoring `done.output[:STDOUT_HEAD_CHARS]` would leave every helper above
    passing while putting the composition back exactly as it was.
    """
    src = (BONE / "judges.py").read_text(encoding="utf-8")
    assert "run.stdout_head = _capture_excerpt(done.output)" in src, (
        "the capture site no longer routes through _capture_excerpt; a flat "
        "slice there defeats every assertion in this file"
    )
    assert "done.output[:STDOUT_HEAD_CHARS]" not in src
