"""ADR-0001 Phase 0 — OpenTofu Authentik conformance + structure gates.

Two layers:
  1. STRUCTURE (offline, always runs): the nos-authentik-app module encodes the
     nOS-required shape so a service cannot be wired wrong — the guarantee that
     makes the triggering MTI cascade impossible by construction.
  2. PLAN CONFORMANCE (online, skipped without a live tenant + plan JSON): given
     a `tofu plan -json`, assert the nOS invariants over the realized graph.

The structure gates are the ones CI runs (no API needed); they pin the
load-bearing properties of the module + root.
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
MODULE = REPO / "modules/nos-authentik-app"
ROOT = REPO / "terraform/authentik"


# ── Layer 1: structure (offline) ─────────────────────────────────────────────

def test_module_never_creates_oauth2_for_forward_auth():
    """THE guarantee: a proxy-mode service can never get an oauth2 provider, so
    the OAuth2/Proxy MTI shared-base cascade (ADR-0001 trigger) is impossible."""
    main = (MODULE / "main.tf").read_text()
    assert 'count               = local.is_oidc ? 1 : 0' in main, \
        "oauth2 provider must be gated on is_oidc (native_oidc only)"
    assert 'count               = local.is_proxy ? 1 : 0' in main, \
        "proxy provider must be gated on is_proxy (forward_auth/header_oidc)"
    assert 'is_oidc  = var.mode == "native_oidc"' in main
    assert 'is_proxy = !local.is_oidc' in main


def test_module_binds_proxy_to_embedded_outpost():
    """Proxy providers MUST attach to the embedded outpost or forward-auth 404s
    (the outpost-binding gap behind the incident)."""
    main = (MODULE / "main.tf").read_text()
    assert 'resource "authentik_outpost_provider_attachment" "embedded"' in main
    blk = main[main.index('"authentik_outpost_provider_attachment"'):]
    assert "count             = local.is_proxy ? 1 : 0" in blk
    assert "protocol_provider = authentik_provider_proxy.this[0].id" in blk


def test_module_app_always_bound_to_a_provider():
    main = (MODULE / "main.tf").read_text()
    blk = main[main.index('resource "authentik_application" "this"'):]
    assert "protocol_provider = local.is_oidc ?" in blk, \
        "every application must bind to whichever provider its mode creates"


def test_mode_is_validated():
    v = (MODULE / "variables.tf").read_text()
    assert 'contains(["native_oidc", "forward_auth", "header_oidc"], var.mode)' in v


def test_no_terraform_only_opentofu():
    """nOS all-FOSS: OpenTofu (MPL-2.0), never Terraform (BSL). The lockfile must
    be the OpenTofu registry, and no terraform-registry pin may sneak in."""
    lock = (ROOT / ".terraform.lock.hcl").read_text()
    assert "registry.opentofu.org/goauthentik/authentik" in lock
    assert "registry.terraform.io" not in lock


def test_secrets_never_hardcoded_in_hcl():
    """Secrets flow through tfvars.json (gitignored, 0600), never literal HCL."""
    for tf in ROOT.glob("*.tf"):
        body = tf.read_text()
        # the only client_secret reference may be `var.*` plumbing
        for line in body.splitlines():
            if "client_secret" in line and "=" in line:
                rhs = line.split("=", 1)[1].strip()
                # allowed: var.* plumbing, a quoted ref, or a for_each map
                # lookup (lookup(each.value,...) / each.value.client_secret).
                ok = (rhs.startswith("var.") or rhs.startswith('"')
                      or rhs.startswith("lookup(") or rhs.startswith("each.")
                      or rhs.startswith("optional("))  # HCL type decl, not a value
                assert ok, f"unexpected client_secret rhs in HCL: {line}"
                assert "_pw_" not in rhs, f"literal secret in HCL: {line}"


def test_tfvars_and_state_are_gitignored():
    gi = (REPO / ".gitignore").read_text()
    assert "*.auto.tfvars.json" in gi
    assert "terraform.tfstate" in gi
    # but the lockfile (the pin) is tracked
    import subprocess
    r = subprocess.run(
        ["git", "check-ignore", "terraform/authentik/.terraform.lock.hcl"],
        cwd=REPO, capture_output=True)
    assert r.returncode != 0, "the .terraform.lock.hcl pin must be tracked, not ignored"


# ── Layer 2: plan conformance (online, opt-in) ───────────────────────────────

def _plan_json():
    p = os.environ.get("NOS_TOFU_PLAN_JSON")
    if not p or not pathlib.Path(p).is_file():
        pytest.skip("set NOS_TOFU_PLAN_JSON=<tofu show -json tfplan> to run plan conformance")
    return json.loads(pathlib.Path(p).read_text())


def test_plan_every_app_has_a_provider():
    """Every module instance that creates an application must also create its
    provider (proxy XOR oauth2). On a CREATE plan protocol_provider is
    "known after apply" (computed), so we assert resource co-presence per
    module rather than the computed value (the binding itself is pinned by the
    offline test_module_app_always_bound_to_a_provider)."""
    plan = _plan_json()
    for cm in plan.get("planned_values", {}).get("root_module", {}).get("child_modules", []):
        types = [res["type"] for res in cm.get("resources", [])]
        if "authentik_application" in types:
            has_provider = ("authentik_provider_proxy" in types
                            or "authentik_provider_oauth2" in types)
            assert has_provider, \
                f"{cm.get('address')} creates an app but no provider"


def test_plan_forward_auth_has_no_oauth2():
    """A module instance is either proxy or oauth2 — never both. Asserted over
    the realized plan, catching any hand-edit that violates mode coherence."""
    plan = _plan_json()
    by_module = {}
    for cm in plan.get("planned_values", {}).get("root_module", {}).get("child_modules", []):
        addr = cm.get("address", "")
        types = {res["type"] for res in cm.get("resources", [])}
        by_module[addr] = types
    for addr, types in by_module.items():
        assert not ("authentik_provider_oauth2" in types
                    and "authentik_provider_proxy" in types), \
            f"{addr} has BOTH oauth2 and proxy providers (mode incoherence)"


def test_registry_not_play_scoped_loaded():
    """The service registry carries raw Jinja ({{ x_domain }}); loading it
    play-wide (include_vars / vars_files) re-triggers the {{ vars }} eager-
    resolve trap in nos_state (CLAUDE.md). It must only be loaded TASK-scoped
    (a `vars:` lookup on the render task)."""
    task = (REPO / "tasks/tofu-authentik.yml").read_text()
    assert "tofu-authentik-services.yml" in task, "registry reference vanished"
    # no play-scoped loaders of the registry
    for n, line in enumerate(task.splitlines(), 1):
        if "tofu-authentik-services.yml" in line:
            ctx = "\n".join(task.splitlines()[max(0, n - 4):n])
            assert "include_vars" not in ctx and "vars_files" not in ctx, \
                f"registry loaded play-scoped near line {n} — use task-scoped vars"
    # it must be a lookup (task-scoped)
    assert "lookup('file'" in task and "from_yaml" in task
