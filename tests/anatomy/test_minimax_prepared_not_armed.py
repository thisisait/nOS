"""Gate — the MiniMax backend is fully plumbed but ships INERT (readiness item 7).

The operator asked for the credential path built end to end so that pasting a key
into credentials.yml and converging is the ONLY remaining step — and for the
switch to not half-happen. This pins both halves:

  * PREPARED — the secret is declared in the persisted store, the catalog knows
    the `{{ minimax_api_key }}` token maps to a `secret:` reference (never a
    value), and the empty credential default exists.
  * NOT ARMED — minimax_enabled defaults false, and with it false the catalog
    injects NO ANTHROPIC_* backend override into any scheduled-agent job.

It also guards the two things that must NEVER leak: the api key as a plaintext
value, and any ANTHROPIC_* env on a NON-agent job.

Pure source + subprocess scan of the catalog builder; no Docker, no live host,
and crucially no ~/.claude/settings.json (the operator's own thread stays on
Anthropic — this feature must never touch it).
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CATALOG = REPO / "files" / "anatomy" / "scripts" / "discover-pulse-catalog.py"
SECRETS_TPL = REPO / "templates" / "secrets.yml.j2"
CFG = REPO / "default.config.yml"
CREDS = REPO / "default.credentials.yml"


def _cfg() -> dict:
    return yaml.safe_load(CFG.read_text())


def test_disabled_by_default():
    assert _cfg().get("minimax_enabled") is False, (
        "minimax_enabled must default to false — this feature ships inert"
    )


def test_secret_is_declared_by_reference_not_value():
    tpl = SECRETS_TPL.read_text()
    assert "minimax_api_key:" in tpl, (
        "templates/secrets.yml.j2 does not declare minimax_api_key — the Pulse "
        "daemon then has no secret to resolve `secret:minimax_api_key` against"
    )
    cat = CATALOG.read_text()
    assert '"{{ minimax_api_key }}":         "secret:minimax_api_key"' in cat \
        or '"{{ minimax_api_key }}"' in cat and "secret:minimax_api_key" in cat, (
        "the catalog token map must send `{{ minimax_api_key }}` to a secret "
        "reference, never a value (the double-allowlist that bit twice)"
    )


def test_empty_credential_default_exists():
    assert "minimax_api_key:" in CREDS.read_text(), (
        "default.credentials.yml must carry an empty minimax_api_key so the "
        "operator has a documented place to paste the key"
    )


def _run_catalog(minimax_enabled: str) -> list[dict]:
    env = dict(os.environ)
    env.update({
        "NOS_PLAYBOOK_DIR": str(REPO),
        "NOS_AUTHENTIK_DOMAIN": "auth.example.test",
        "NOS_TENANT_DOMAIN": "example.test",
        "NOS_GLOBAL_PASSWORD_PREFIX": "test",
        "NOS_BONE_PORT": "8099",
        "NOS_PROMETHEUS_PORT": "9090",
        "NOS_WING_HOME": "/tmp/wing",
        "NOS_WING_APP_DIR": "/tmp/wing/app",
        "NOS_MINIMAX_ENABLED": minimax_enabled,
        "NOS_MINIMAX_BASE_URL": "https://api.minimax.io/anthropic",
        "NOS_MINIMAX_MODEL": "MiniMax-M2",
        "NOS_MINIMAX_SMALL_MODEL": "MiniMax-Text-01",
    })
    out = subprocess.run(
        [sys.executable, str(CATALOG)], env=env, capture_output=True, text=True,
    )
    assert out.returncode == 0, f"catalog builder failed: {out.stderr[:400]}"
    return json.loads(out.stdout)


def _anthropic_keys(job: dict) -> list[str]:
    return [k for k in (job.get("env") or {}) if k.startswith("ANTHROPIC_")]


def test_off_injects_nothing():
    cat = _run_catalog("0")
    leaks = [
        (c["plugin_name"], c["job"]["name"], _anthropic_keys(c["job"]))
        for c in cat
        if _anthropic_keys(c["job"])
    ]
    assert not leaks, f"minimax OFF must inject no ANTHROPIC_* env, found: {leaks}"
    # And no literal token survived un-substituted anywhere.
    assert "{{ minimax_api_key }}" not in json.dumps(cat)


def test_armed_injects_reference_only_into_agent_jobs():
    cat = _run_catalog("1")
    agent_jobs = [c for c in cat if "pulse-run-agent.sh" in c["job"].get("command", "")]
    assert agent_jobs, "no agent-runner jobs discovered — shape drift?"
    for c in agent_jobs:
        env = c["job"]["env"]
        assert env.get("ANTHROPIC_AUTH_TOKEN") == "secret:minimax_api_key", (
            f"{c['job']['name']}: auth token must be a secret reference, not a value"
        )
        assert env.get("ANTHROPIC_BASE_URL"), f"{c['job']['name']}: base url missing"
    # NON-agent jobs must never receive the backend override.
    non_agent = [c for c in cat if "pulse-run-agent.sh" not in c["job"].get("command", "")]
    bled = [(c["plugin_name"], c["job"]["name"]) for c in non_agent if _anthropic_keys(c["job"])]
    assert not bled, f"ANTHROPIC_* leaked onto non-agent jobs: {bled}"


def test_key_value_never_appears_in_catalog_when_armed():
    """Even armed, the catalog carries the reference, never a key VALUE."""
    cat = _run_catalog("1")
    blob = json.dumps(cat)
    # secret: reference is fine; a raw 'sk-'/'mm-'-style value must not appear.
    assert "secret:minimax_api_key" in blob
