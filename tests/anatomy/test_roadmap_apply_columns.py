"""roadmap-apply-columns reconciles a NAMED column and touches nothing else.

The whole reason the tool is per-column: a full-columns PATCH would drop the
live-only `when` column and rewrite the deliberate `status` board. These pin
that reconcile() reshapes only what it is told and preserves the column set.
"""
import importlib.util
import pathlib

import pytest

_MOD = pathlib.Path(__file__).resolve().parents[2] / "tools" / "roadmap-apply-columns.py"


def _load():
    spec = importlib.util.spec_from_file_location("rac", _MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # import is I/O-free — keap_api is imported lazily in call()
    return mod


RECONCILE = _load().reconcile

LIVE = [
    {"key": "track", "kind": "select", "role": "dimension", "required": False,
     "options": ["release", "security", "platform"]},
    {"key": "status", "kind": "select", "options": ["shipped", "active", "next"]},
    {"key": "when", "kind": "text"},  # live-only column — must survive
]
DECLARED = {
    "track": {"key": "track", "label": "Track", "kind": "text", "role": "dimension"},
    "status": {"key": "status", "kind": "select",
               "options": ["inbox", "triaged", "queued", "shipped", "active", "next"]},
}


def test_track_becomes_text_and_loses_options():
    out = RECONCILE(LIVE, DECLARED, {"track"})
    track = next(c for c in out if c["key"] == "track")
    assert track["kind"] == "text"
    assert "options" not in track


def test_column_set_is_never_changed():
    out = RECONCILE(LIVE, DECLARED, {"track"})
    assert [c["key"] for c in out] == [c["key"] for c in LIVE]  # `when` survives


def test_unnamed_columns_are_untouched():
    out = RECONCILE(LIVE, DECLARED, {"track"})
    assert next(c for c in out if c["key"] == "status") == LIVE[1]
    assert next(c for c in out if c["key"] == "when") == LIVE[2]


def test_refuses_a_column_absent_from_either_side():
    with pytest.raises(KeyError):
        RECONCILE(LIVE, DECLARED, {"nonesuch"})   # not live
    with pytest.raises(KeyError):
        RECONCILE(LIVE, DECLARED, {"when"})        # live but not declared
