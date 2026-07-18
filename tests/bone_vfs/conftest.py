"""Fixtures for the Bone VFS module (files/anatomy/bone/vfs.py).

Loads vfs.py directly (same importlib trick as tests/bone_auth) and mounts its
router on a throwaway FastAPI app over a temp doctrine tree, so the containment
gate can be exercised without a running Bone.
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
def vfs_env(tmp_path, monkeypatch):
    """A doctrine tree with two users; returns (data_root, users_dir)."""
    slug = "t"
    monkeypatch.setenv("NOS_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("NOS_TENANT_SLUG", slug)
    monkeypatch.setenv("BONE_VFS_TOKEN", TOKEN)

    users = tmp_path / "tenants" / slug / "users"
    (users / "alice" / "documents").mkdir(parents=True)
    (users / "alice" / "documents" / "hello.txt").write_text("hi from alice", encoding="utf-8")
    (users / "bob").mkdir(parents=True)
    (users / "bob" / "secret.txt").write_text("bob's private data", encoding="utf-8")
    return tmp_path, users


@pytest.fixture
def client(vfs_env):
    sys.modules.pop("bone_vfs_under_test", None)
    vfs = _load("bone_vfs_under_test", BONE_DIR / "vfs.py")
    app = FastAPI()
    app.include_router(vfs.router)
    return TestClient(app)


@pytest.fixture
def auth():
    return {"Authorization": f"Bearer {TOKEN}"}
