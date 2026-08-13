"""Gate — MiniMax stays PREPARED, NOT ARMED; and the catalog carries no backend.

REWRITTEN ONCE, 2026-08-13, as `w-agentkit-spine` said it would be. The first
version of this gate asserted that, when armed, EVERY scheduled-agent job
carried the ANTHROPIC_* override — the estate-wide shape ruling 1
(docs/minimax-groundwork.md) forbids. The gate was enforcing what the ruling
prohibited, which is why implementation was deferred into the spine rather
than patched here: per-job selection encoded in `pulse_jobs.env_json` would
have been built twice and this gate rewritten twice with it.

THE CONTRACT NOW:

  * PREPARED — the key has a documented place to be pasted
    (default.credentials.yml), a persisted home (~/.nos/secrets.yml via
    templates/secrets.yml.j2), and a registry entry that resolves it by
    REFERENCE (state/llm-backends.yml, `nos:minimax_api_key`).
  * NOT ARMED — minimax_enabled defaults false, and arming renders
    NOS_ARMED_BACKENDS into wing.plist where App\\AgentKit\\BindingResolver
    reads it. Routing additionally requires a per-agent `model.backend`
    declaration that agrees with that agent's Article-30 record — gated by
    test_a_binding_reads_the_register.py, not here.
  * THE CATALOG CARRIES NO BACKEND, EVER. discover-pulse-catalog.py must not
    emit a single ANTHROPIC_* env key or minimax secret reference on ANY job,
    armed or not — the shell-bridge ceremonies always run on the default
    backend, which is ruling 1's fail-closed default. The armed state is
    exercised here by feeding the catalog the OLD arming envs and requiring
    them to change nothing: the flag must no longer be able to reach the
    catalog's output at all.
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
REGISTRY = REPO / "state" / "llm-backends.yml"
WING_PLIST = REPO / "roles" / "pazny.wing" / "templates" / "wing.plist.j2"


def test_disabled_by_default():
    cfg = yaml.safe_load(CFG.read_text())
    assert cfg.get("minimax_enabled") is False, (
        "minimax_enabled must default to false — this feature ships inert"
    )


def test_the_credential_path_is_prepared_end_to_end():
    assert "minimax_api_key:" in CREDS.read_text(), (
        "default.credentials.yml must carry an empty minimax_api_key so the "
        "operator has a documented place to paste the key"
    )
    assert "minimax_api_key:" in SECRETS_TPL.read_text(), (
        "templates/secrets.yml.j2 no longer persists minimax_api_key — the "
        "binding resolver then has nothing to resolve `nos:minimax_api_key` "
        "against and arming fails at session open"
    )
    registry = yaml.safe_load(REGISTRY.read_text())
    ref = registry["backends"]["minimax"]["auth_secret"]
    assert ref == "nos:minimax_api_key", (
        f"the registry resolves {ref!r} — the three declarations above and "
        "this one must name the same key or the chain breaks silently"
    )


def test_arming_renders_into_the_plist_not_the_catalog():
    plist = WING_PLIST.read_text()
    assert "NOS_ARMED_BACKENDS" in plist and "minimax_enabled" in plist, (
        "wing.plist.j2 no longer renders NOS_ARMED_BACKENDS from "
        "minimax_enabled — the flag would arm nothing anywhere, or worse, "
        "something somewhere else"
    )


def _run_catalog(extra_env: dict[str, str]) -> list[dict]:
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
    })
    env.update(extra_env)
    out = subprocess.run(
        [sys.executable, str(CATALOG)], env=env, capture_output=True, text=True,
    )
    assert out.returncode == 0, f"catalog builder failed: {out.stderr[:400]}"
    return json.loads(out.stdout)


def test_the_catalog_carries_no_backend_env_armed_or_not():
    # The OLD arming envs are deliberately fed in the "armed" case: they used
    # to inject ANTHROPIC_* into every agent job, and the assertion is that
    # they can no longer reach the output at all.
    for label, extra in (
        ("unarmed", {"NOS_MINIMAX_ENABLED": "0"}),
        ("armed", {
            "NOS_MINIMAX_ENABLED": "1",
            "NOS_MINIMAX_BASE_URL": "https://api.minimax.io/anthropic",
            "NOS_MINIMAX_MODEL": "MiniMax-M2",
            "NOS_MINIMAX_SMALL_MODEL": "MiniMax-Text-01",
        }),
    ):
        cat = _run_catalog(extra)
        assert cat, "catalog is empty — the sweep below would pass by absence"
        offenders = [
            (c["plugin_name"], c["job"]["name"], k)
            for c in cat
            for k in (c["job"].get("env") or {})
            if k.startswith("ANTHROPIC_")
        ]
        assert not offenders, (
            f"[{label}] the catalog put a backend env on a job again: "
            f"{offenders}. Backend selection is a per-agent AgentKit binding "
            "(state/llm-backends.yml); the catalog re-growing an injection is "
            "the estate-wide shape ruling 1 forbids, rebuilt."
        )
        blob = json.dumps(cat)
        assert "minimax" not in blob.lower(), (
            f"[{label}] a minimax reference appeared in the catalog output — "
            "the key or its secret reference is riding job env again"
        )
