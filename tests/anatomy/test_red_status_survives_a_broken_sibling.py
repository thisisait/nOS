"""A sibling reader that raises is UNKNOWN in red-status, never a traceback.

undeclared() and santa() exec tools/undeclared-status.py and santa-status.py
unguarded; one bad plist or Linux-only gap took the whole first-read of a
session down. Readers exit 0 and name what they could not read.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


def _red():
    spec = importlib.util.spec_from_file_location("_red_sibling", REPO / "tools" / "red-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("fn", ["undeclared", "santa"])
def test_a_missing_sibling_is_unknown(fn, tmp_path, monkeypatch) -> None:
    red = _red()
    monkeypatch.setattr(red, "REPO", tmp_path)  # sibling file absent -> exec raises
    out = getattr(red, fn)()
    assert out["items"] == []
    assert len(out["missing"]) == 1 and "-status.py" in out["missing"][0]
