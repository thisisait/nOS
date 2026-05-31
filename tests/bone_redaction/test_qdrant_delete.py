"""Bone Qdrant client — points/delete unit tests.

Pins the per-subject erasure seam that Art. 17 needs: the Qdrant client must be
able to issue POST /collections/<c>/points/delete by id-list OR by filter (the
control redaction.py's header flags as missing, and the hard prerequisite for
batch-3 P0-ART17-REACH). Loads files/anatomy/bone/clients/qdrant_client.py
directly (same importlib trick test_redaction.py uses) and stubs httpx.Client
so no network is touched — the assertions are on the request the client BUILDS:
URL path, ?wait=true, and the selector body shape.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
QDRANT_CLIENT = ROOT / "files" / "anatomy" / "bone" / "clients" / "qdrant_client.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """Captures the single POST the client makes; returns a canned 2xx."""

    last_calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None):
        _FakeClient.last_calls.append({"url": url, "json": json})
        return _FakeResponse({"result": {"operation_id": 1, "status": "completed"}})


@pytest.fixture
def qc(monkeypatch):
    sys.modules.pop("qdrant_client_under_test", None)
    mod = _load("qdrant_client_under_test", QDRANT_CLIENT)
    _FakeClient.last_calls = []
    monkeypatch.setattr(mod.httpx, "Client", _FakeClient)
    # A configured client — URL non-empty so _require() passes.
    return mod.QdrantClient(url="http://127.0.0.1:6333", api_key="k", timeout=5)


def test_method_exists_on_client(qc):
    assert hasattr(qc, "delete_points") and callable(qc.delete_points)


def test_delete_by_ids_builds_points_body(qc):
    out = qc.delete_points("agent_outputs", ids=["a", "b", 3])
    call = _FakeClient.last_calls[-1]
    assert call["url"] == "http://127.0.0.1:6333/collections/agent_outputs/points/delete?wait=true"
    assert call["json"] == {"points": ["a", "b", 3]}
    assert out == {"operation_id": 1, "status": "completed"}


def test_delete_by_filter_builds_filter_body(qc):
    flt = {"must": [{"key": "subject_email", "match": {"value": "x@y.io"}}]}
    qc.delete_points("agent_outputs", filter=flt)
    call = _FakeClient.last_calls[-1]
    assert call["json"] == {"filter": flt}
    assert "/points/delete?wait=true" in call["url"]


def test_requires_exactly_one_selector(qc):
    with pytest.raises(ValueError):
        qc.delete_points("c")  # neither
    with pytest.raises(ValueError):
        qc.delete_points("c", ids=["a"], filter={"must": []})  # both
    # No request must have been built for the rejected calls.
    assert _FakeClient.last_calls == []


def test_unconfigured_client_raises_notconfigured(qc):
    mod = sys.modules["qdrant_client_under_test"]
    empty = mod.QdrantClient(url="", api_key="", timeout=5)
    with pytest.raises(mod.NotConfigured):
        empty.delete_points("c", ids=["a"])
