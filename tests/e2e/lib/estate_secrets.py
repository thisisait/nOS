"""Read one estate credential for a probe — never print it.

Order: a value persisted in ~/.nos/secrets.yml under that key, else the v2
derived leaf named in files/anatomy/secrets/registry.yml (the same HKDF
derivation the playbook and tools/nos-secret.py use). Anything else is None,
and the probe that asked for it fails naming the key, not the value.
"""
from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))
import nos_secret_derive as derive  # noqa: E402


@lru_cache(maxsize=1)
def _store() -> dict:
    p = Path.home() / ".nos/secrets.yml"
    return (yaml.safe_load(p.read_text()) or {}) if p.is_file() else {}


@lru_cache(maxsize=1)
def _registry() -> dict:
    return derive.load_registry(str(REPO / "files/anatomy/secrets/registry.yml"))


def secret(key: str) -> str | None:
    store = _store()
    if store.get(key):
        return str(store[key])
    entry = _registry().get(key)
    master = store.get("nos_secret_master")
    if entry and master and store.get("nos_secret_scheme") == "v2":
        return derive.estate_leaf(derive.master_bytes(str(master)), entry["service"], entry["purpose"])
    return None


def identity_password(password_var: str) -> str | None:
    """A nos_identities password_var: persisted under that name, else the
    registry leaf its default.credentials.yml declaration derives from."""
    m = re.search(rf'^{re.escape(password_var)}:\s*"\{{\{{ nos_derived_secrets\.([a-z0-9_]+) \}}\}}"',
                  (REPO / "default.credentials.yml").read_text(), re.M)
    return secret(password_var) or (secret(m.group(1)) if m else None)
