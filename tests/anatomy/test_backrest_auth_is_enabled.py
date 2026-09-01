"""Anatomy gate — backrest must not serve its config to anyone who can reach the port.

Measured 2026-09-01 (roadmap sec-backrest-auth, REM-214): an unauthenticated
POST /v1.Backrest/GetConfig from inside devops-gitea-1 returned 200 with the
whole config — hook commands and the sync identity keyId included. A 127.0.0.1
bind constrains HOST callers only; Docker Desktop forwards host-gateway to the
host loopback and 23 containers carry such an alias.

Two halves, because either alone is a false pass:
  1. `enable-auth.py` is EXECUTED here, not read. It must turn auth on, mint a
     bcrypt the password actually verifies against, and stay a no-op afterwards
     — including on the daemon-rewritten shape, where protojson has DROPPED
     `"disabled": false` and a naive reader sees "auth off" and re-hashes forever.
  2. The role must run it, and must then READ the running daemon (401) instead
     of trusting the script's own report of what it attempted.

CI-safe: temp files + htpasswd only. No daemon, no Docker, no network.
"""
from __future__ import annotations

import base64
import json
import pathlib
import secrets
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles" / "pazny.backrest"
SCRIPT = ROLE / "files" / "enable-auth.py"
TASKS = ROLE / "tasks" / "main.yml"

HTPASSWD = shutil.which("htpasswd") or shutil.which("htpasswd", path="/usr/sbin:/usr/bin")
needs_htpasswd = pytest.mark.skipif(not HTPASSWD, reason="htpasswd (apache2-utils) not installed")


def _run(config: pathlib.Path, password: str) -> str:
    out = subprocess.run(["python3", str(SCRIPT), "--config", str(config), "--user", "admin"],
                         input=password, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _stored_hash(cfg: dict, user: str = "admin") -> str:
    users = (cfg.get("auth") or {}).get("users") or []
    row = next(u for u in users if u.get("name") == user)
    hashed = base64.b64decode(row["passwordBcrypt"]).decode()
    assert hashed.startswith("$2"), f"not a bcrypt hash: {hashed[:4]}"
    return hashed


@needs_htpasswd
def test_it_enables_auth_and_the_hash_verifies(tmp_path):
    password = secrets.token_urlsafe(18)  # minted here — never a committed literal
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"version": 6, "instance": "x", "auth": {"disabled": True}}))

    assert _run(config, password) == "CHANGED"
    cfg = json.loads(config.read_text())
    assert cfg["auth"]["disabled"] is False
    assert cfg["instance"] == "x", "the rest of the daemon-owned config must survive"

    hashed = _stored_hash(cfg)
    htfile = tmp_path / "htpasswd"
    htfile.write_text(f"admin:{hashed}\n")
    assert subprocess.run([HTPASSWD, "-vb", str(htfile), "admin", password],
                          capture_output=True).returncode == 0
    assert subprocess.run([HTPASSWD, "-vb", str(htfile), "admin", password + "x"],
                          capture_output=True).returncode != 0


@needs_htpasswd
def test_it_is_a_noop_once_auth_is_on(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"version": 6, "auth": {"disabled": True}}))
    _run(config, secrets.token_urlsafe(18))
    before = config.read_text()
    assert _run(config, secrets.token_urlsafe(18)) == "UNCHANGED"
    assert config.read_text() == before, "a re-hash every run churns the daemon config"


@needs_htpasswd
def test_the_daemon_rewritten_shape_reads_as_enabled(tmp_path):
    """protojson omits `disabled: false` — a missing key is auth ON, not OFF."""
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"version": 6, "auth": {
        "users": [{"name": "admin", "passwordBcrypt": base64.b64encode(b"$2y$10$x").decode()}]}}))
    assert _run(config, secrets.token_urlsafe(18)) == "UNCHANGED"


@needs_htpasswd
def test_a_foreign_user_does_not_count_as_our_login(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"version": 6, "auth": {"users": [{"name": "someone-else"}]}}))
    assert _run(config, secrets.token_urlsafe(18)) == "CHANGED"
    names = [u["name"] for u in json.loads(config.read_text())["auth"]["users"]]
    assert names == ["someone-else", "admin"], "an existing operator user must survive"


def _tasks() -> list:
    return yaml.safe_load(TASKS.read_text())


def test_the_role_runs_the_reconcile_with_the_password_off_argv():
    cmds = [t["ansible.builtin.command"] for t in _tasks() if "ansible.builtin.command" in t]
    runs = [c for c in cmds if isinstance(c, dict) and "enable-auth.py" in str(c.get("argv", ""))]
    assert runs, "the seed template cannot carry a bcrypt — the script must run"
    assert "stdin" in runs[0], "the password belongs on stdin, not in argv (visible in ps)"
    assert not any("password" in str(a) for a in runs[0]["argv"]), "password leaked into argv"


def test_the_role_reads_the_daemon_rather_than_trusting_the_script():
    probes = [t["ansible.builtin.uri"] for t in _tasks() if "ansible.builtin.uri" in t
              and "GetConfig" in str(t["ansible.builtin.uri"].get("url", ""))]
    assert probes, "no reader proves an unauthenticated RPC is refused"
    assert probes[0].get("status_code") == [401], "the probe must REQUIRE 401, not accept 200"
    assert all("failed_when" not in t for t in _tasks()
               if t.get("ansible.builtin.uri") in probes), "a tolerated probe proves nothing"
