"""loop:review's refusal reaches the run record, not only stderr.

MEASURED 2026-10-09 on a clean client machine: red-status showed `loop:review`
rc=2 with "install_gitlab is false — reviewing on Gitea" — the announcement,
not the reason. rc=2 is a declared failure (plugin.yml: Refused, configuration
it will not guess at), so red is right; but Pulse records only STDOUT in
pulse_runs.stdout_tail, and the refusal was printed to stderr alone. The
operator saw a decision where there was a defect.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_the_refusal_is_on_stdout(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("_loop_review_rec", REPO / "tools/loop-review.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def refuse(*_a, **_k):
        raise mod.Refused("Gitea did not list pull requests (HTTP 401)")

    monkeypatch.setattr(mod, "open_requests", refuse)
    monkeypatch.setattr("sys.argv", ["loop-review.py"])
    assert mod.main() == 2
    out = capsys.readouterr()
    assert "HTTP 401" in out.out, "the refusal never reaches pulse_runs.stdout_tail"
    assert "HTTP 401" in out.err, "stderr keeps the refusal too (the off-forge gate reads it)"
