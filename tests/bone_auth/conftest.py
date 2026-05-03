"""Test fixtures for Bone's JWT auth module.

We import auth.py directly from files/anatomy/bone/ (moved from
files/bone/ in anatomy A3a, 2026-05-03) — same trick the existing
callback tests use to load wing_telemetry.py without packaging the bone
sources as a real Python distribution.
"""

from __future__ import annotations

import importlib.util
import os
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
def auth_mod(monkeypatch):
    """Load files/anatomy/bone/auth.py with a deterministic test issuer."""
    monkeypatch.setenv("AUTHENTIK_OIDC_ISSUER", "https://auth.test.example/application/o/")
    monkeypatch.setenv("AUTHENTIK_JWKS_URL", "https://auth.test.example/application/o/jwks/")
    monkeypatch.setenv("BONE_REQUIRE_JWT_AUTH", "1")
    # Drop any previously-imported copy so env vars are picked up fresh.
    sys.modules.pop("bone_auth_under_test", None)
    return _load("bone_auth_under_test", BONE_DIR / "auth.py")
