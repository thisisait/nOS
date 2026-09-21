"""Importer /rows writes go through digest_absorb.absorb after check_bundle.

digest-absorb-chokepoint: run_importer is a helper a CLI can skip. absorb() is
the shared POST. If it does not refuse an ungated bundle, a caller that never
ran the gate still writes — the review's "convention, not a chokepoint".

Scope is the digest-import surface, not MCP/roadmap (those are operator doors).
raw-never-touches-knowledge stays pending until raw-archive + capture doors.
"""
from __future__ import annotations

import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
ABSORB = REPO / "tools" / "digest_absorb.py"


def _da():
    spec = importlib.util.spec_from_file_location("digest_absorb", ABSORB)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_import_clis_do_not_post_rows():
    """A /rows Request in a CLI is a bypass of absorb()."""
    hits = []
    for p in sorted((REPO / "tools").glob("digest-import*.py")):
        src = p.read_text()
        if "/rows" in src and "Request" in src:
            hits.append(str(p.relative_to(REPO)))
    assert not hits, "importer CLI posts /rows itself — bypasses absorb:\n  " + "\n  ".join(hits)


def test_absorb_source_calls_check_bundle_before_post():
    src = ABSORB.read_text()
    fn = src.split("def absorb", 1)[1].split("\ndef ", 1)[0]
    assert "check_bundle" in fn
    assert fn.find("check_bundle") < fn.find("_post_row")


def test_post_row_strips_keap_private_columns(monkeypatch):
    import json
    posted = []
    da = _da()

    def fake_urlopen(req, timeout=15):
        posted.append(json.loads(req.data))

        class _R:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        return _R()

    monkeypatch.setattr(da.urllib.request, "urlopen", fake_urlopen)
    da._post_row("pending-invoice-verify", {"slug": "x", "__sharing": {}, "__id": "1"}, {})
    assert posted == [{"slug": "x"}]


def test_ungated_bundle_does_not_post(monkeypatch):
    da = _da()
    posts = []
    monkeypatch.setattr(da, "_post_row", lambda *a, **k: posts.append(a))
    monkeypatch.setattr(da, "ensure_table", lambda *a, **k: None)
    monkeypatch.setattr(da, "_existing_slugs", lambda *a, **k: set())
    monkeypatch.setattr(da, "rw_token", lambda: "x")
    monkeypatch.setattr(da, "proxy_header", lambda: {})
    # untrusted, no _prov → check_bundle must refuse
    rc = da.absorb({"meta": {"trusted": False}, "deterministic": {
        "party": [{"slug": "bypass", "legal_name": "Nope"}],
    }})
    assert rc == 1
    assert posts == []
