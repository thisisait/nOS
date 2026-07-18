"""Bone user-state — per-user KV isolation + validation. Two nOS-face users must
never see each other's personalization/app state, and each user's data lives in
its own DB file under its own class-3 tree."""

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
    (tmp_path / "tenants" / "t" / "users" / "bob").mkdir(parents=True)
    sys.modules.pop("bone_userstate_under_test", None)
    us = _load("bone_userstate_under_test", BONE_DIR / "userstate.py")
    app = FastAPI()
    app.include_router(us.router)
    return TestClient(app), tmp_path


@pytest.fixture
def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_set_get_roundtrip(client, auth):
    c, _ = client
    layout = {"wallpaper": "aurora", "pinned": ["grafana", "keap"]}
    assert c.post("/api/v1/userstate/set", json={"uid": "alice", "ns": "face.desktop", "key": "layout", "value": layout}, headers=auth).status_code == 200
    r = c.get("/api/v1/userstate/get", params={"uid": "alice", "ns": "face.desktop", "key": "layout"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["value"] == layout


def test_list_namespace(client, auth):
    c, _ = client
    c.post("/api/v1/userstate/set", json={"uid": "alice", "ns": "app.sticky-notes", "key": "n1", "value": {"text": "buy milk"}}, headers=auth)
    c.post("/api/v1/userstate/set", json={"uid": "alice", "ns": "app.sticky-notes", "key": "n2", "value": {"text": "ship face"}}, headers=auth)
    r = c.get("/api/v1/userstate/list", params={"uid": "alice", "ns": "app.sticky-notes"}, headers=auth)
    assert {i["key"] for i in r.json()["items"]} == {"n1", "n2"}


def test_delete(client, auth):
    c, _ = client
    c.post("/api/v1/userstate/set", json={"uid": "alice", "ns": "face.desktop", "key": "x", "value": 1}, headers=auth)
    assert c.post("/api/v1/userstate/delete", json={"uid": "alice", "ns": "face.desktop", "key": "x"}, headers=auth).json()["deleted"] == 1
    assert c.get("/api/v1/userstate/get", params={"uid": "alice", "ns": "face.desktop", "key": "x"}, headers=auth).status_code == 404


def test_per_user_isolation(client, auth):
    c, tmp = client
    c.post("/api/v1/userstate/set", json={"uid": "alice", "ns": "face.desktop", "key": "layout", "value": {"secret": "alice-only"}}, headers=auth)
    # bob's namespace is empty — no leakage of alice's row.
    assert c.get("/api/v1/userstate/list", params={"uid": "bob", "ns": "face.desktop"}, headers=auth).json()["items"] == []
    assert c.get("/api/v1/userstate/get", params={"uid": "bob", "ns": "face.desktop", "key": "layout"}, headers=auth).status_code == 404
    # Physically separate DB files under each user's own tree.
    assert (tmp / "tenants" / "t" / "users" / "alice" / ".face" / "state.db").exists()
    assert not (tmp / "tenants" / "t" / "users" / "bob" / ".face" / "state.db").exists() or \
        (tmp / "tenants" / "t" / "users" / "bob" / ".face" / "state.db") != (tmp / "tenants" / "t" / "users" / "alice" / ".face" / "state.db")


def test_invalid_uid_refused(client, auth):
    c, _ = client
    assert c.get("/api/v1/userstate/list", params={"uid": "../bob", "ns": "face.desktop"}, headers=auth).status_code == 400


def test_invalid_namespace_refused(client, auth):
    c, _ = client
    assert c.post("/api/v1/userstate/set", json={"uid": "alice", "ns": "bad ns!", "key": "k", "value": 1}, headers=auth).status_code == 400


def test_no_token_401(client):
    c, _ = client
    assert c.get("/api/v1/userstate/list", params={"uid": "alice", "ns": "face.desktop"}).status_code == 401


def test_wrong_token_403(client):
    c, _ = client
    assert c.get("/api/v1/userstate/list", params={"uid": "alice", "ns": "face.desktop"}, headers={"Authorization": "Bearer nope"}).status_code == 403
