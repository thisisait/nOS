"""A loaded host makes KEAP slow; slow must not read as unreachable.

MEASURED 2026-09-23. The first live pipeline-exercise cycle extracted its
document, parked the original, and then died with `REFUSING: KEAP unreadable
(timed out)` — while `qwen3:14b` (14.9 GB) sat resident in VRAM. That is the
estate's known host budget (a resident 14B took the KEAP API from ~0.09s to
~25s), and every digest tool used a flat 15s deadline, so the whole family
failed whenever a big model was warm — including the production sweep that a
photographed invoice goes through, right after the VLM it just ran.

One retry at a doubled deadline rescues the loaded host. It must NOT rescue a
down one: after the retry the timeout still raises and the caller still
refuses, which is the difference between patience and pretending.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))

_spec = importlib.util.spec_from_file_location("digest_absorb", REPO / "tools" / "digest_absorb.py")
DA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DA)


class _Resp:
    def read(self):
        return b"{}"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_slow_call_is_retried_once_with_a_longer_deadline(monkeypatch):
    seen: list[float] = []

    def fake(req, timeout=None):
        seen.append(timeout)
        if len(seen) == 1:
            raise TimeoutError("too slow")
        return _Resp()

    monkeypatch.setattr(DA.urllib.request, "urlopen", fake)
    with DA._open(object()):
        pass
    assert len(seen) == 2, "a slow KEAP was not retried"
    assert seen[1] == seen[0] * 2, "the retry did not lengthen the deadline"


def test_a_down_keap_still_raises(monkeypatch):
    """The defect this must NOT introduce: patience that never gives up."""
    calls = []

    def always_slow(req, timeout=None):
        calls.append(timeout)
        raise TimeoutError("down")

    monkeypatch.setattr(DA.urllib.request, "urlopen", always_slow)
    with pytest.raises(TimeoutError):
        DA._open(object())
    assert len(calls) == 2, "it must try exactly twice, then surface the timeout"


def test_the_deadline_is_tunable_for_a_loaded_host(monkeypatch):
    monkeypatch.setenv("NOS_KEAP_TIMEOUT_S", "60")
    spec = importlib.util.spec_from_file_location("da2", REPO / "tools" / "digest_absorb.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._TIMEOUT_S == 60


def test_every_digest_call_goes_through_it():
    """A call site left on a flat urlopen would fail on exactly the host this
    exists for, and nothing would say so."""
    src = (REPO / "tools" / "digest_absorb.py").read_text(encoding="utf-8")
    body = src.split("def _open(", 1)[1].split("\ndef ", 1)[0]
    outside = src.replace(body, "")
    assert "urlopen(req" not in outside, (
        "a KEAP call still bypasses _open — it will fail while a model is warm")
