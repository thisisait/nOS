"""Anatomy gate — EspoCRM's SSO is hands-off, end to end, offline-verifiable.

Context: apps/espocrm.yml onboarded EspoCRM as a Tier-2 manifest app with
`nginx.auth: oidc`, but shipped WITHOUT a top-level `authentik:` block. That
block, not `nginx.auth`, is what load_plugins.run_aggregators's
`from: app_manifest` source reads (module_utils/load_plugins.py, the
`from_kind == "app_manifest"` branch) into authentik-base's `inputs.clients`
— the same path documenso/qdrant/roundcube/twofauth use. Without it Authentik
never provisions an OAuth2Provider for espocrm at all: not a "operator must
click a button" gap, a missing object. RETRO-RED: `git show
c274d6b6:apps/espocrm.yml` (the commit that onboarded the manifest) has no
`authentik:` key — `test_espocrm_harvested_by_real_aggregator` below fails
against that revision (harvested list has no slug=='espocrm' entry) and
passes once the block lands (this change).

Second half: EspoCRM's own OIDC client (Administration -> Authentication ->
OIDC) has no env-var/entrypoint wiring upstream — it's a Settings-entity row.
`roles/pazny.apps_runner/tasks/post.yml`'s "EspoCRM hands-off OIDC config"
task PUTs it via `/api/v1/Settings` (verified against espocrm/espocrm develop
source: Controllers/Settings.php + entityDefs/Settings.json) using the
bootstrap admin credential the manifest already generates. This file pins
that the client_id/secret POSTed there match what the manifest actually
provisions Authentik-side — the two are hand-typed in two files and drift
silently otherwise.

The live PUT itself (the actual EspoCRM instance answering `/api/v1/Settings`)
needs a running converge — NOT exercised here. What IS exercised offline: the
manifest schema/parser, the real aggregator harvest (same code path core-up
runs, with fake template_vars standing in for the real `{{ vars }}` context),
and the post-hook's rendered payload/gating as an AST fact, not prose.
"""

from __future__ import annotations

import importlib
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO / "apps/espocrm.yml"
POST_HOOK_PATH = REPO / "roles/pazny.apps_runner/tasks/post.yml"
REGISTRY_PATH = REPO / "files/anatomy/secrets/registry.yml"

sys.path.insert(0, str(REPO / "files/anatomy"))
sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST_PATH.read_text())


def test_espocrm_manifest_still_parses():
    """Non-negotiable: adding SSO wiring must not break the smoke-parse."""
    from module_utils.nos_app_parser import parse_app_file

    record = parse_app_file(str(MANIFEST_PATH))
    assert record["meta"]["name"] == "espocrm"


def test_espocrm_embedded_mariadb_is_1189():
    """REM-266: the apps-stack MariaDB must track the infra pin (11.8.9),
    not a leftover 11.8.8 tag the shared role already left."""
    text = MANIFEST_PATH.read_text()
    assert "docker.io/mariadb:11.8.9" in text
    assert "mariadb:11.8.8" not in text


def test_espocrm_declares_authentik_block():
    record = _manifest()
    auth = record.get("authentik")
    assert isinstance(auth, dict), (
        "apps/espocrm.yml has no top-level `authentik:` block — the real "
        "aggregator harvest (load_plugins.run_aggregators, from_kind== "
        "'app_manifest') reads exactly this key, not `nginx.auth`. Without "
        "it Authentik never provisions a provider for espocrm."
    )
    assert auth.get("mode") == "native_oidc", (
        "espocrm has its own built-in OIDC client (core since v7.3) — this "
        "is a real per-user native_oidc service, not a forward_auth gate."
    )
    assert auth.get("client_id") == "nos-espocrm"
    assert "nos_derived_secrets.oidc_espocrm" in (auth.get("client_secret") or "")
    assert auth.get("slug") == "espocrm"
    assert auth.get("enabled") is True


def test_espocrm_registered_in_secret_registry():
    # Flat text search rather than parsing registry.yml's nested shape — this
    # gate only cares that the key exists and points at the right service.
    text = REGISTRY_PATH.read_text()
    assert "oidc_espocrm:" in text, (
        "files/anatomy/secrets/registry.yml has no `oidc_espocrm` entry — "
        "`nos_derived_secrets.oidc_espocrm` (referenced by apps/espocrm.yml's "
        "authentik.client_secret) would abort the HKDF derivation with an "
        "unregistered-key error."
    )
    assert 'service: "espocrm"' in text.split("oidc_espocrm:", 1)[1].split("\n", 1)[0]


def test_espocrm_harvested_by_real_aggregator():
    """Run the ACTUAL aggregator (core-up.yml's code path) against the real
    plugins/ + apps/ trees, with fake template_vars standing in for the real
    `{{ vars }}` context main.yml snapshots as `nos_plugin_ctx`. Proves the
    Jinja in the authentik: block renders, not just that the YAML parses."""
    import load_plugins as lp
    importlib.reload(lp)

    plugins = lp.discover(REPO / "files/anatomy/plugins")
    apps = []
    for p in (REPO / "apps").glob("*.yml"):
        if p.name.startswith("_") or ".draft" in p.name:
            continue
        data = yaml.safe_load(p.read_text())
        if isinstance(data, dict):
            apps.append(data)

    fake_vars = {
        "nos_derived_secrets": {"oidc_espocrm": "FAKE-SECRET-FOR-TEST"},
        "tenant_domain": "test.local",
    }
    lp.run_aggregators(plugins, app_manifests=apps, template_vars=fake_vars)

    authentik_plugin = next(p for p in plugins if p.name == "authentik-base")
    clients = authentik_plugin.inputs.get("clients") or []
    espocrm_clients = [c for c in clients if c.get("slug") == "espocrm"]
    assert espocrm_clients, (
        "espocrm never appears in the aggregator's harvested inputs.clients "
        "— the authentik: block is missing or malformed, so Authentik would "
        "never provision an OAuth2Provider for it."
    )
    entry = espocrm_clients[0]
    assert entry.get("mode") == "native_oidc"
    assert entry.get("client_id") == "nos-espocrm"
    assert entry.get("client_secret") == "FAKE-SECRET-FOR-TEST", (
        "client_secret did not render through the fake nos_derived_secrets "
        "context — the manifest's Jinja expression is wrong."
    )
    assert entry.get("tier") == 2
    redirects = entry.get("redirect_uris") or []
    assert redirects and "test.local" in redirects[0], (
        "redirect_uris did not render tenant_domain"
    )


def _find_task(tasks: list, name: str) -> dict:
    for t in tasks:
        if t.get("name") == name:
            return t
    raise AssertionError(f"post.yml no longer has a task named {name!r}")


def _flatten_block_tasks(tasks: list) -> list:
    out = []
    for t in tasks:
        out.append(t)
        if "block" in t:
            out.extend(_flatten_block_tasks(t["block"]))
    return out


def test_post_hook_payload_matches_manifest_client_id():
    top_tasks = yaml.safe_load(POST_HOOK_PATH.read_text())
    all_tasks = _flatten_block_tasks(top_tasks)
    uri_task = _find_task(
        all_tasks,
        "[Apps Post] PUT /api/v1/Settings — EspoCRM native OIDC, hands-off",
    )
    body = uri_task["ansible.builtin.uri"]["body"]

    manifest_auth = _manifest()["authentik"]
    assert body["oidcClientId"] == manifest_auth["client_id"], (
        "post-hook oidcClientId and the manifest's authentik.client_id have "
        "drifted apart — EspoCRM would be told to trust a client_id "
        "Authentik never provisioned."
    )
    assert "nos_derived_secrets.oidc_espocrm" in body["oidcClientSecret"]
    for required_key in (
        "oidcAuthorizationEndpoint", "oidcTokenEndpoint",
        "oidcUserInfoEndpoint", "oidcJwksEndpoint", "authenticationMethod",
    ):
        assert required_key in body, f"post-hook payload missing {required_key}"
    # Pure-SSO doctrine: no standing bypass for anyone but the bootstrap admin.
    assert body["oidcAllowRegularUserFallback"] is False
    assert body["oidcAllowAdminUser"] is True


def test_post_hook_gated_on_espocrm_presence_and_oidc_mode():
    top_tasks = yaml.safe_load(POST_HOOK_PATH.read_text())
    all_tasks = _flatten_block_tasks(top_tasks)
    oidc_task = _find_task(all_tasks, "[Apps Post] EspoCRM hands-off OIDC config")
    conditions = " ".join(oidc_task.get("when") or [])
    assert "_apps_espocrm.id" in conditions and "'espocrm'" in conditions
    assert "_apps_espocrm.auth_mode" in conditions and "'oidc'" in conditions
    assert "install_authentik" in conditions
