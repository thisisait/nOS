"""A single pass cannot tell a gap from a drift.

MEASURED 2026-08-30, the same 22 samples through the same code hours apart:

    hermes3:8b     17/22  then  14/22      <- three samples of drift
    qwen3:14b      22/22  then  22/22
    MiniMax-M2.7   20/22  then  21/22

The harness exists to answer ONE question — at which model size does one_shot
extraction stop working, and is a bigger model dramatically better — and that
question is entirely about the SIZE of a difference. With one pass per subject
it could not distinguish a three-sample gap between two models from a
three-sample drift in one, and it had already been used to report a ranking
(17 / 16 / 17 on weakness-triage) that the noise floor does not support.

So `score()` takes `repeat`, pools the counters, and reports `runs` (each
pass's exact count) and `spread`. A one-element `runs` list is the caveat
rather than the absence of one: it says out loud that nobody repeated this.

Behavioural, through score() with a stub runner whose answer alternates — a
source assertion could not tell pooling from a loop that overwrites.

Retro-verified 2026-08-30 by making score() ignore `repeat`.
"""

from __future__ import annotations

import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
STUB = REPO / "tests/anatomy/_stub_alternating_runner.sh"


def _harness():
    spec = importlib.util.spec_from_file_location(
        "ops_harness_repeat", REPO / "tools/nos-ops-harness.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _score(repeat: int) -> dict:
    return _harness().score(
        binding={"backend": "stub", "model": "stub", "size_b": 0, "model_env": None},
        samples=[{"id": "a", "input": "x", "expect": {"v": 1}}],
        meta={}, agent="ops-extract", cmd=["sh", str(STUB)], timeout=30,
        repeat=repeat)


def test_repeat_runs_the_family_more_than_once() -> None:
    """The stub answers correctly on odd calls and wrongly on even ones, so a
    pooled four-pass run must be 2/4 — not 1/1 four times over, and not 4/4."""
    got = _score(4)
    assert got["attempted"] == 4, (
        f"four passes over one sample attempted {got['attempted']}; `repeat` is "
        "not reaching the sample loop")
    assert got["runs"] == [1, 0, 1, 0], (
        f"per-pass exacts were {got['runs']}; expected the stub's alternation. "
        "If they are all equal the passes are not independent runs.")
    assert got["exact"] == 2 and got["accuracy"] == 0.5


def test_the_spread_is_reported_and_a_single_run_says_so() -> None:
    """`spread` is the number that decides whether a difference between two
    subjects is real. A one-pass run reports spread 0 AND a one-element `runs`,
    which is what stops 0 reading as 'stable'."""
    many = _score(4)
    assert many["spread"] == 1, f"alternating stub gave spread {many['spread']}"
    one = _score(1)
    assert one["runs"] == [1] and one["spread"] == 0, (
        "a single pass must still carry `runs`, or the report cannot be told "
        "apart from a repeated one that happened to be stable")
