"""espo-party-sync — KEAP party → Espo Account payload, no network."""
from __future__ import annotations

import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "espo_party_sync", REPO / "tools" / "espo-party-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_account_payload_carries_the_join_key():
    mod = _load()
    p = mod.account_payload({"slug": "party-ico-25596641", "legal_name": "Buyer s.r.o.",
                             "role": "client"})
    assert p["name"] == "Buyer s.r.o."
    assert "nos:party:party-ico-25596641" in p["description"]
    assert p["type"] == "Customer"
