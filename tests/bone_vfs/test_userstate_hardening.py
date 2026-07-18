"""Bone user-state hardening — the namespace/key regexes and the 256 KB value
cap are the whole validation surface for the per-user KV store. This module
proves an XSS payload stored as a VALUE round-trips INERT (a JSON string, never
executed), that oversized values are refused with 413, and that the strict
ns/key regexes reject the adversarial matrix — i.e. nothing was loosened.

Doctrine: pytest, prescriptive assertion messages. Incident this prevents: a
face app persisting attacker-controlled text (a sticky-note body, a saved
search) must never let that text become executable, and a runaway value must
never blow past the KV cap into blob territory.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
BONE_DIR = ROOT / "files" / "anatomy" / "bone"
TOKEN = "vfs-test-secret"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("NOS_TENANT_SLUG", "t")
    monkeypatch.setenv("BONE_VFS_TOKEN", TOKEN)
    (tmp_path / "tenants" / "t" / "users" / "alice").mkdir(parents=True)
    sys.modules.pop("bone_userstate_hardening", None)
    us = _load("bone_userstate_hardening", BONE_DIR / "userstate.py")
    app = FastAPI()
    app.include_router(us.router)
    return TestClient(app)


@pytest.fixture
def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# ── XSS payload as a VALUE round-trips inert ─────────────────────────────────

def test_xss_string_value_roundtrips_inert(client, auth):
    payload = '<script>alert(document.cookie)</script><img src=x onerror=alert(1)>'
    set_r = client.post(
        "/api/v1/userstate/set",
        json={"uid": "alice", "ns": "app.sticky-notes", "key": "n1", "value": payload},
        headers=auth,
    )
    assert set_r.status_code == 200, "storing an XSS string value must succeed (it is inert data)"
    get_r = client.get(
        "/api/v1/userstate/get",
        params={"uid": "alice", "ns": "app.sticky-notes", "key": "n1"},
        headers=auth,
    )
    assert get_r.status_code == 200
    assert get_r.json()["value"] == payload, "XSS value must round-trip byte-exact"
    assert "application/json" in get_r.headers["content-type"], "value is served as JSON, never HTML"


def test_xss_nested_in_json_value_roundtrips(client, auth):
    payload = {"text": "<script>evil()</script>", "tags": ["</table>", "‮exe"]}
    client.post(
        "/api/v1/userstate/set",
        json={"uid": "alice", "ns": "app.sticky-notes", "key": "n2", "value": payload},
        headers=auth,
    )
    r = client.get(
        "/api/v1/userstate/get",
        params={"uid": "alice", "ns": "app.sticky-notes", "key": "n2"},
        headers=auth,
    )
    assert r.json()["value"] == payload, "nested XSS inside a JSON value must round-trip unchanged"


def test_unicode_value_roundtrips(client, auth):
    payload = {"note": "héllo 世界 🎉 — ünïcödé"}
    client.post(
        "/api/v1/userstate/set",
        json={"uid": "alice", "ns": "face.desktop", "key": "u", "value": payload},
        headers=auth,
    )
    r = client.get("/api/v1/userstate/get", params={"uid": "alice", "ns": "face.desktop", "key": "u"}, headers=auth)
    assert r.json()["value"] == payload, "UTF-8 JSON value must round-trip byte-exact"


# ── Oversized values rejected (413) ──────────────────────────────────────────

def test_oversized_value_rejected_413(client, auth):
    big = "x" * (256 * 1024 + 1)  # one byte over the 256 KB cap
    r = client.post(
        "/api/v1/userstate/set",
        json={"uid": "alice", "ns": "face.desktop", "key": "big", "value": big},
        headers=auth,
    )
    assert r.status_code == 413, f"a value over the 256 KB cap must be 413, got {r.status_code}"


def test_value_just_under_cap_accepted(client, auth):
    # A JSON string of ~200 KB encodes under the cap and must be accepted.
    ok = "y" * (200 * 1024)
    r = client.post(
        "/api/v1/userstate/set",
        json={"uid": "alice", "ns": "face.desktop", "key": "ok", "value": ok},
        headers=auth,
    )
    assert r.status_code == 200, "a value under the cap must be accepted"


# ── The ns/key regexes are still strict (nothing loosened) ───────────────────

@pytest.mark.parametrize(
    "ns",
    ["bad ns!", "../etc", "UPPER", ".dot", "-lead", "ns/slash", "ns\x00nul",
     "<script>", "a" * 65, ""],
)
def test_invalid_namespace_rejected(client, auth, ns):
    r = client.post(
        "/api/v1/userstate/set",
        json={"uid": "alice", "ns": ns, "key": "k", "value": 1},
        headers=auth,
    )
    assert r.status_code == 400, f"namespace {ns!r} must be refused"


@pytest.mark.parametrize(
    "key",
    ["bad key!", "../escape", "key/slash", "key\x00nul", "<script>", ".lead", "a" * 129, ""],
)
def test_invalid_key_rejected(client, auth, key):
    r = client.post(
        "/api/v1/userstate/set",
        json={"uid": "alice", "ns": "face.desktop", "key": key, "value": 1},
        headers=auth,
    )
    assert r.status_code == 400, f"key {key!r} must be refused"


@pytest.mark.parametrize("uid", ["../bob", "..", ".", "a/b", ".hidden"])
def test_invalid_uid_rejected(client, auth, uid):
    r = client.post(
        "/api/v1/userstate/set",
        json={"uid": uid, "ns": "face.desktop", "key": "k", "value": 1},
        headers=auth,
    )
    assert r.status_code == 400, f"uid {uid!r} must be refused"
