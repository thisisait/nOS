"""iris-bench --domain reads the generated nos-assay cases too, cut by --tier; a plain case has no depth.

Operator ruling 2026-10-16: generated cases (cases.generated.yml, tier smoke < standard < full) run
beside the hand-written ones; depth is reported only for a case scored turn by turn.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _bench():
    spec = importlib.util.spec_from_file_location("iris_bench", REPO / "tools/iris-bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def assay(tmp_path, monkeypatch):
    d = tmp_path / "domains/d1"
    d.mkdir(parents=True)
    (d / "cases.yml").write_text("- {id: hand, kind: count, prompt: p}\n")
    (d / "cases.generated.yml").write_text("- {id: s, kind: count, tier: smoke, prompt: p}\n"
                                           "- {id: st, kind: count, tier: standard, prompt: p}\n"
                                           "- {id: f, kind: count, tier: full, prompt: p}\n")
    monkeypatch.setenv("NOS_ASSAY_DIR", str(tmp_path))
    return tmp_path


def test_a_tier_takes_its_own_and_every_smaller_tier(assay):
    b = _bench()
    ids = lambda tier: [c["id"] for c in b.load_cases("x.yml", "d1", tier)]  # noqa: E731
    assert ids("smoke") == ["hand", "s"]
    assert ids("standard") == ["hand", "s", "st"]
    assert ids("full") == ["hand", "s", "st", "f"]
    assert ids(None) == ["hand"]  # no --tier: the hand-written cases alone, as before


def test_an_unknown_tier_is_refused(assay):
    with pytest.raises(SystemExit):
        _bench().load_cases("x.yml", "d1", "huge")


def test_a_plain_case_has_no_depth():
    b = _bench()
    assert b.case_depth({"prompt": "p"}, [{"index": 0, "status": "fail", "failed": []}]) is None
    turns = [{"index": 0, "status": "pass"}, {"index": 1, "status": "fail"}]
    assert b.case_depth({"turns": [{"say": "a", "checks": {}}, {"say": "b", "checks": {}}]}, turns) == 1
