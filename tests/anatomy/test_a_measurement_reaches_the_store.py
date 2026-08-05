"""A number that is measured and then dropped is worse than one never taken.

MEASURED 2026-08-05 against the live estate: `pulse_runs` holds 17,254 rows.
Every one carries `finished_at`, `exit_code` and `stdout_tail`. **Not one carries
`duration_ms.**

Nothing was broken along the way, which is why it lasted:

  * `pulse/runners/subprocess.py` TIMES every path it can return through —
    success, timeout, command-not-found, allowlist refusal — and puts the result
    in `RunResult.duration_s`.
  * `pulse/wing_client.py::post_run_finish` had no parameter for it, so the
    payload left without it.
  * Wing's `PulseRepository::recordFinish` reads `duration_ms` from the body and
    writes it — correctly, and it never arrived.
  * `app/Presenters/PulsePresenter.php` SELECTs the column for the operator's
    /pulse page, which therefore rendered an empty cell beside every job, every
    night, for the life of the scheduler.

Four layers, one missing argument, and each layer was individually right.

WHY IT MATTERS BEYOND A BLANK COLUMN. The nightly chain — keap-consolidate →
cortex-fs-sync → keap-embed-sync → keap-features-sync → keap-lint →
cortex-corpus-diff — is ordered by nothing but cron minutes, 15 apart. Today the
jobs take seconds and the headroom is enormous. The column that would show that
stopping to be true is the one that was never written, so the first sign of a
job outgrowing its slot would be the NEXT job reading half-built state.

THE DISCIPLINE THIS ENCODES, and it is the session's recurring one: the duration
is reported only by the branch that took it. The dry-run path executed nothing;
the daemon-exception path may have run for any length before throwing. Both omit
the field rather than send 0, because a zero is a measurement and "we did not
look" is not.

CI-safe: source reading plus the existing mocked-daemon harness. No HTTP, no
launchd, no live estate.
"""

from __future__ import annotations

import ast
import re
import time
from pathlib import Path
from unittest.mock import MagicMock

from pulse.config import PulseConfig
from pulse.daemon import PulseDaemon

REPO = Path(__file__).resolve().parents[2]
PULSE = REPO / "files/anatomy/pulse/pulse"
RUNNER = PULSE / "runners/subprocess.py"
CLIENT = PULSE / "wing_client.py"
DAEMON = PULSE / "daemon.py"
WING_REPO = REPO / "files/anatomy/wing/app/Model/PulseRepository.php"
WING_UI = REPO / "files/anatomy/wing/app/Presenters/PulsePresenter.php"


def _config(tmp_path, **overrides) -> PulseConfig:
    base = dict(
        wing_api_base="http://127.0.0.1:9000",
        wing_api_token="test-token",
        tick_interval_s=30.0,
        state_dir=tmp_path,
        log_path=tmp_path / "p.log",
        max_concurrent_runs=4,
        dry_run=False,
    )
    base.update(overrides)
    return PulseConfig(**base)


def _drain(daemon: PulseDaemon, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with daemon._inflight_lock:
            if not daemon._inflight:
                return
        time.sleep(0.05)


def test_the_runner_still_measures_every_path():
    """The measurement is the part that was never missing — keep it that way.

    Every `RunResult(...)` in the runner must carry `duration_s`. If one branch
    stops timing itself, the field it feeds goes quietly back to null for that
    class of run only, which is the hardest version of this bug to see.
    """
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    constructions = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "RunResult"
    ]
    assert len(constructions) >= 4, (
        f"only {len(constructions)} RunResult branches found; the runner used to "
        f"have four (ok / timeout / not-found / refused)"
    )
    for call in constructions:
        assert any(kw.arg == "duration_s" for kw in call.keywords), (
            f"a RunResult at line {call.lineno} is built without duration_s — "
            f"that branch reports no measurement at all"
        )


def test_the_client_forwards_the_duration():
    source = CLIENT.read_text(encoding="utf-8")
    assert "duration_ms" in source, (
        "post_run_finish no longer carries duration_ms, so the runner's "
        "measurement is dropped in transport again"
    )
    assert re.search(r"if duration_ms is not None", source), (
        "duration_ms is sent unconditionally; an unmeasured run would then "
        "report a number (0) where there is none"
    )


def test_the_measured_duration_is_the_one_that_is_sent(tmp_path, monkeypatch):
    """The behavioural half, aimed at the layer that was actually broken.

    An earlier draft ran a real `sleep` and asserted the elapsed time. It failed
    at 0 ms — SEC H-PULSE1's execution-boundary allowlist refused `/bin/sleep`
    (`/bin/` is not a permitted prefix), then refused `python3 -c …` because
    `_ARG_RE` bans spaces and semicolons. The gate caught its own test twice,
    which is two security guards working, and it was the wrong shape: to time a
    real subprocess it would have had to disable both.

    The defect was never in the measurement — the runner has always timed every
    path — it was that `post_run_finish` had no parameter to carry it. So feed a
    RunResult with a KNOWN duration and assert that number arrives. That is the
    link that was missing, tested with nothing switched off.
    """
    from pulse.runners.subprocess import RunResult

    monkeypatch.setattr(
        "pulse.daemon.sp_runner.execute",
        lambda *a, **k: RunResult(exit_code=0, stdout_tail="", stderr_tail="",
                                  duration_s=1.234, timed_out=False),
    )
    wing = MagicMock()
    wing.list_due_jobs.return_value = []
    daemon = PulseDaemon(_config(tmp_path), wing=wing)
    assert daemon._dispatch(
        {"id": "t", "command": "/opt/homebrew/bin/true", "args": [],
         "max_runtime_s": 30}) is True
    _drain(daemon)

    wing.post_run_finish.assert_called_once()
    kwargs = wing.post_run_finish.call_args.kwargs
    assert "duration_ms" in kwargs, "the daemon finished a real run without a duration"
    assert kwargs["duration_ms"] == 1234, (
        f"the runner measured 1.234 s and the client was handed "
        f"{kwargs['duration_ms']!r} — the number that travels is not the number "
        f"that was measured"
    )


def test_a_dry_run_reports_no_duration(tmp_path):
    """Absence stays absence: nothing ran, so nothing is timed."""
    wing = MagicMock()
    wing.list_due_jobs.return_value = []
    daemon = PulseDaemon(_config(tmp_path, dry_run=True), wing=wing)
    assert daemon._dispatch(
        {"id": "t", "command": "/bin/true", "args": [], "max_runtime_s": 5}) is True
    _drain(daemon)

    kwargs = wing.post_run_finish.call_args.kwargs
    assert kwargs.get("duration_ms") is None, (
        f"a dry run reported duration_ms={kwargs.get('duration_ms')!r}; it "
        f"executed nothing, and 0 would read as an instant run rather than an "
        f"absent one"
    )


def test_the_exception_path_does_not_invent_one():
    """Read from source: the failure branch has no measurement to report."""
    tree = ast.parse(DAEMON.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            for call in ast.walk(handler):
                if (isinstance(call, ast.Call)
                        and getattr(call.func, "attr", None) == "post_run_finish"):
                    assert not any(kw.arg == "duration_ms" for kw in call.keywords), (
                        f"the exception handler at line {call.lineno} reports a "
                        f"duration for a run that may have thrown at any point"
                    )


def test_the_store_and_the_page_are_still_waiting_for_it():
    """The consumers were always there — this pins that the fix has somewhere to land."""
    assert "duration_ms" in WING_REPO.read_text(encoding="utf-8"), (
        "Wing's recordFinish no longer persists duration_ms, so the newly sent "
        "value would be dropped one layer later instead"
    )
    assert "duration_ms" in WING_UI.read_text(encoding="utf-8"), (
        "the operator's /pulse page no longer reads duration_ms"
    )
