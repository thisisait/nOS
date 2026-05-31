"""Bone embeddings PII redaction — unit tests.

Pins the control declared by qdrant-base/plugin.yml `bone_redaction_required:
true`: email addresses MUST be stripped from an embeddings-upsert payload before
it reaches Qdrant (which has no per-point erasure path). Loads
files/anatomy/bone/redaction.py directly (same trick the bone_auth tests use).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BONE_DIR = ROOT / "files" / "anatomy" / "bone"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def red(monkeypatch):
    monkeypatch.delenv("BONE_EMBED_REDACT", raising=False)
    sys.modules.pop("bone_redaction_under_test", None)
    return _load("bone_redaction_under_test", BONE_DIR / "redaction.py")


def test_strips_email_from_flat_payload(red):
    out = red.redact_payload({"note": "ping admin@dev.local about the CVE"})
    assert "admin@dev.local" not in out["note"]
    assert "[redacted-email]" in out["note"]


def test_strips_email_in_nested_dict_and_list(red):
    payload = {
        "context": {"author": "Jan Novák <jan.novak@example.cz>"},
        "tags": ["owner=ops@nos.local", "sev=high"],
    }
    out = red.redact_payload(payload)
    assert "jan.novak@example.cz" not in str(out)
    assert "ops@nos.local" not in str(out)
    assert out["tags"][1] == "sev=high"  # non-email strings untouched


def test_none_and_non_string_scalars_pass_through(red):
    assert red.redact_payload(None) is None
    out = red.redact_payload({"score": 0.97, "count": 3, "ok": True})
    assert out == {"score": 0.97, "count": 3, "ok": True}


def test_disable_via_env_returns_payload_verbatim(red, monkeypatch):
    monkeypatch.setenv("BONE_EMBED_REDACT", "false")
    sys.modules.pop("bone_redaction_under_test", None)
    red2 = _load("bone_redaction_under_test", BONE_DIR / "redaction.py")
    payload = {"note": "reach me at admin@dev.local"}
    assert red2.redact_payload(payload) == payload


def test_multiple_emails_in_one_string(red):
    out = red.redact_payload({"thread": "from a@x.io to b@y.io cc c@z.io"})
    assert "@" not in out["thread"]
    assert out["thread"].count("[redacted-email]") == 3
