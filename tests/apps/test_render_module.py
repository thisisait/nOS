"""Unit tests for library/nos_apps_render.py.

Covers:
  - per-app processing (happy path: TLS/SSO/EU clean)
  - gate violations surface with app id + gate name
  - magic-token resolution inside compose dict
  - authentik_entry shape per auth_mode
  - Traefik labels per auth_mode
  - smoke_entry / wing_system / registry_entry / kuma_monitor shapes
  - apps_dir scan filters (_*, .draft, non-yml)

The module is invoked at the function level (_process_one). The full
AnsibleModule wrapper (main()) is exercised via a tiny in-memory shim in
test_main_smoke().
"""

from __future__ import absolute_import, division, print_function

import importlib.util
import json
import os
import sys

import pytest


# Load library/nos_apps_render.py without going through Ansible's plugin
# loader (we don't have an inventory in unit tests).
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)


def _load_render_module():
    """Import library/nos_apps_render.py without Ansible runtime."""
    path = os.path.join(ROOT, "library", "nos_apps_render.py")
    spec = importlib.util.spec_from_file_location("nos_apps_render", path)
    mod = importlib.util.module_from_spec(spec)
    # AnsibleModule import will fail under pytest — that's fine, we only call
    # the helper functions, never main().
    sys.modules["nos_apps_render"] = mod
    try:
        spec.loader.exec_module(mod)
    except ImportError as exc:
        if "ansible" not in str(exc).lower():
            raise
        # AnsibleModule import failed — patch it out and re-import
        import types
        ansible_pkg = types.ModuleType("ansible")
        sys.modules["ansible"] = ansible_pkg
        module_utils_pkg = types.ModuleType("ansible.module_utils")
        sys.modules["ansible.module_utils"] = module_utils_pkg
        basic_mod = types.ModuleType("ansible.module_utils.basic")
        basic_mod.AnsibleModule = type("AnsibleModule", (), {})
        sys.modules["ansible.module_utils.basic"] = basic_mod
        # Stub the parser passthrough import too
        from module_utils import nos_app_parser  # noqa: F401
        nap_pkg = types.ModuleType("ansible.module_utils.nos_app_parser")
        for k in ("parse_app_file", "gate_tls_required", "gate_sso_required",
                  "gate_eu_residency", "resolve_tokens", "AppParseError"):
            setattr(nap_pkg, k, getattr(nos_app_parser, k))
        sys.modules["ansible.module_utils.nos_app_parser"] = nap_pkg
        spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def render():
    return _load_render_module()


# ---------------------------------------------------------------------------
# Fixture builders

def _record(meta_overrides=None, gdpr_overrides=None, compose_overrides=None,
            nginx_overrides=None):
    """Build a parser-valid manifest record."""
    record = {
        "meta": {
            "name": "demo",
            "version": "1.0",
            "summary": "demo app",
            "category": "productivity",
            "ports": [8080],
        },
        "gdpr": {
            "purpose": "demo processing",
            "legal_basis": "legitimate_interests",
            "data_categories": ["email"],
            "data_subjects": ["partners"],
            "retention_days": 90,
            "processors": [],
            "transfers_outside_eu": False,
        },
        "compose": {
            "services": {
                "demo": {
                    "image": "ghcr.io/demo/demo:1",
                    "environment": [
                        "DB_USER=$SERVICE_USER_DB",
                        "DB_PASS=$SERVICE_PASSWORD_DB",
                    ],
                    "ports": ["8080:8080"],
                },
            },
        },
    }
    if meta_overrides:
        record["meta"].update(meta_overrides)
    if gdpr_overrides:
        record["gdpr"].update(gdpr_overrides)
    if compose_overrides:
        record["compose"] = compose_overrides
    if nginx_overrides:
        record["nginx"] = nginx_overrides
    return record


def _write_app(tmp_path, name, record):
    import yaml
    path = tmp_path / "{}.yml".format(name)
    path.write_text(yaml.safe_dump(record, sort_keys=False))
    return str(path)


# ---------------------------------------------------------------------------
# Per-app processing — happy path

class TestHappyPath(object):
    def test_clean_app_produces_full_shape(self, render, tmp_path):
        path = _write_app(tmp_path, "demo", _record())
        app, secrets, violations = render._process_one(
            path,
            tenant_domain="dev.local",
            apps_subdomain="apps",
            secret_seed={},
            extra_eu_registries=[],
            strict=False,
            traefik_network="shared_net",
        )
        assert violations == []
        assert app is not None
        assert app["id"] == "demo"
        assert app["fqdn"] == "demo.apps.dev.local"
        assert app["auth_mode"] == "proxy"  # default
        assert app["category"] == "productivity"
        assert "PASSWORD_DB" in secrets["demo"]
        assert app["secrets_used"] == ["PASSWORD_DB"]
        # Token actually resolved inside compose
        env = app["compose"]["services"]["demo"]["environment"]
        assert any(e.startswith("DB_USER=demo_db") for e in env)
        # Traefik label set
        assert any("Host(`demo.apps.dev.local`)" in lbl for lbl in app["traefik_labels"])
        assert any("entrypoints=websecure" in lbl for lbl in app["traefik_labels"])
        # Auth=proxy → forward-auth middleware
        assert any("authentik@file" in lbl for lbl in app["traefik_labels"])

    def test_apps_subdomain_can_be_empty(self, render, tmp_path):
        path = _write_app(tmp_path, "demo", _record())
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert app["fqdn"] == "demo.dev.local"

    # ── Track F: host_alias plumbing ──────────────────────────────────────────

    def test_host_alias_inserts_segment(self, render, tmp_path):
        """host_alias='lab' yields <app>.lab.<apps_subdomain>.<tenant_domain>."""
        path = _write_app(tmp_path, "demo", _record())
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            host_alias="lab",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert app["fqdn"] == "demo.lab.apps.dev.local"
        # Traefik Host rule must match the new FQDN — drift here means the
        # router won't accept requests at the URL the env vars advertise.
        assert any("Host(`demo.lab.apps.dev.local`)" in lbl
                   for lbl in app["traefik_labels"])

    def test_host_alias_empty_byte_identical(self, render, tmp_path):
        """Empty host_alias → pre-Track-F output (FQDN drops the segment)."""
        path = _write_app(tmp_path, "demo", _record())
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            host_alias="",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert app["fqdn"] == "demo.apps.dev.local"

    def test_host_alias_with_no_apps_subdomain(self, render, tmp_path):
        """Tier-1-style: host_alias only (no apps_subdomain)."""
        path = _write_app(tmp_path, "demo", _record())
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="",
            host_alias="lab",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert app["fqdn"] == "demo.lab.dev.local"

    def test_generated_secrets_round_trip_through_yaml(self, render, tmp_path):
        """Regression test for the blockinfile indent drift bug:
        generated_secrets must round-trip through PyYAML safe_load when
        emitted via to_nice_yaml — that's the canonical credentials.yml
        persistence path. Catches regressions if the dict shape changes
        in a way that produces colon-bait values (e.g. URLs as values
        without quoting).
        """
        import yaml as _yaml
        path = _write_app(tmp_path, "demo", _record())
        _, secrets, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        # Mimic the persist task in roles/pazny.apps_runner/tasks/main.yml
        # — wrap under app_secrets, dump via safe_dump (Ansible's
        # to_nice_yaml uses the same emitter).
        emitted = _yaml.safe_dump(
            {"app_secrets": secrets}, default_flow_style=False, indent=2,
            width=200,
        )
        # Round-trip must succeed and preserve every value
        loaded = _yaml.safe_load(emitted)
        assert "app_secrets" in loaded
        assert loaded["app_secrets"]["demo"]["PASSWORD_DB"] == secrets["demo"]["PASSWORD_DB"]

    def test_service_fqdn_token_in_env_matches_traefik_route(self, render, tmp_path):
        """Regression test for the FQDN resolver subdomain-blindness:
        $SERVICE_FQDN_DEMO inside compose env strings used to resolve to
        ``demo.dev.local`` while the Traefik route was emitted as
        ``demo.apps.dev.local`` — apps would advertise a hostname with
        no route. Both must use the same FQDN now.
        """
        rec = _record(compose_overrides={
            "services": {
                "demo": {
                    "image": "ghcr.io/demo/demo:1",
                    "environment": [
                        "PUBLIC_URL=https://$SERVICE_FQDN_DEMO/",
                        "CALLBACK=https://$SERVICE_FQDN_DEMO/auth/callback",
                    ],
                    "ports": ["8080:8080"],
                },
            },
        })
        path = _write_app(tmp_path, "demo", rec)
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        env = app["compose"]["services"]["demo"]["environment"]
        # Env vars use the same hostname Traefik routes
        assert any("PUBLIC_URL=https://demo.apps.dev.local/" in e for e in env)
        assert any("CALLBACK=https://demo.apps.dev.local/auth/callback" in e for e in env)
        # And the Traefik label confirms the same FQDN
        assert any("Host(`demo.apps.dev.local`)" in lbl for lbl in app["traefik_labels"])

    def test_secret_seed_pins_existing_passwords(self, render, tmp_path):
        path = _write_app(tmp_path, "demo", _record())
        seed = {"demo": {"PASSWORD_DB": "PERSISTED-XYZ"}}
        app, secrets, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed=seed, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        env = app["compose"]["services"]["demo"]["environment"]
        assert any("DB_PASS=PERSISTED-XYZ" in e for e in env)
        # Generated_secrets returns the FULL set used (seeded + new) so the
        # runner persists everything back to credentials.yml. That keeps the
        # next run idempotent without losing context about which seeds were
        # consumed.
        assert secrets["demo"]["PASSWORD_DB"] == "PERSISTED-XYZ"


# ---------------------------------------------------------------------------
# Auth mode wiring

class TestAuthModes(object):
    def test_oidc_mode_emits_redirect_uri(self, render, tmp_path):
        rec = _record(nginx_overrides={"auth": "oidc",
                                       "oidc_callback": "/api/sso/cb"})
        path = _write_app(tmp_path, "demo", rec)
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert app["auth_mode"] == "oidc"
        assert app["authentik_entry"]["redirect_uris"].endswith("/api/sso/cb")
        # OIDC mode → no proxy middleware
        assert not any("authentik@file" in lbl for lbl in app["traefik_labels"])
        # security-headers + compress still applied
        assert any("security-headers@file" in lbl for lbl in app["traefik_labels"])

    def test_none_mode_skips_authentik_entry(self, render, tmp_path):
        rec = _record(nginx_overrides={"auth": "none"})
        path = _write_app(tmp_path, "demo", rec)
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert app["auth_mode"] == "none"
        assert app["authentik_entry"] is None
        # No forward-auth middleware
        assert not any("authentik@file" in lbl for lbl in app["traefik_labels"])

    def test_proxy_mode_authentik_entry_has_external_host(self, render, tmp_path):
        path = _write_app(tmp_path, "demo", _record())
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert app["authentik_entry"]["type"] == "proxy"
        assert app["authentik_entry"]["external_host"] == "https://demo.apps.dev.local"


# ---------------------------------------------------------------------------
# Gate violations

class TestGates(object):
    def test_gate_sso_violation_when_consent_with_auth_none(self, render, tmp_path):
        rec = _record(
            gdpr_overrides={"legal_basis": "consent",
                            "data_subjects": ["partners"]},
            nginx_overrides={"auth": "none"},
        )
        path = _write_app(tmp_path, "demo", rec)
        app, _, violations = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert any("gate_sso_required" in v for v in violations)
        # Non-strict → app still emitted (operator can review violations)
        assert app is not None

    def test_gate_eu_residency_us_registry(self, render, tmp_path):
        rec = _record(compose_overrides={"services": {
            "demo": {"image": "gcr.io/foo/bar:1", "ports": ["8080:8080"]},
        }})
        path = _write_app(tmp_path, "demo", rec)
        app, _, violations = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert any("gate_eu_residency" in v for v in violations)

    def test_extra_eu_registries_satisfies_residency(self, render, tmp_path):
        rec = _record(compose_overrides={"services": {
            "demo": {"image": "registry.weirdcorp.tld/x:1",
                     "ports": ["8080:8080"]},
        }})
        path = _write_app(tmp_path, "demo", rec)
        _, _, violations = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={},
            extra_eu_registries=["registry.weirdcorp.tld"],
            strict=False, traefik_network="shared_net",
        )
        assert violations == []

    def test_strict_mode_short_circuits(self, render, tmp_path):
        rec = _record(
            gdpr_overrides={"legal_basis": "consent"},
            nginx_overrides={"auth": "none"},
        )
        path = _write_app(tmp_path, "demo", rec)
        app, _, violations = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=True,
            traefik_network="shared_net",
        )
        assert app is None
        assert violations  # at least one


class TestParseFailures(object):
    def test_missing_gdpr_block(self, render, tmp_path):
        bad = _record()
        bad.pop("gdpr")
        path = _write_app(tmp_path, "demo", bad)
        app, _, violations = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert app is None
        assert any("MANDATORY" in v for v in violations)
        # Violations must be tagged with the app id so the operator
        # can locate the offending file in a multi-app run.
        assert all("[demo]" in v for v in violations)


# ---------------------------------------------------------------------------
# Per-app derived shapes

class TestDerivedShapes(object):
    def test_registry_entry_minimal_fields(self, render, tmp_path):
        path = _write_app(tmp_path, "demo", _record())
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        re_ = app["registry_entry"]
        assert re_["name"] == "demo"
        # tier is INT — uniform with Tier-1 entries in service-registry.json.j2
        assert re_["tier"] == 2
        assert isinstance(re_["tier"], int)
        assert re_["stack"] == "apps"
        assert re_["url"] == "https://demo.apps.dev.local/"
        assert re_["port"] == 8080
        # Future-UI metadata
        assert "version" in re_
        assert "homepage" in re_

    def test_wing_system_minimal_fields(self, render, tmp_path):
        path = _write_app(tmp_path, "demo", _record())
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        ws = app["wing_system"]
        assert ws["id"] == "app_demo"
        assert ws["type"] == "app"
        assert ws["stack"] == "apps"
        # Future-UI cross-link metadata
        assert ws["tier"] == 2
        assert ws["rbac_tier"] in (1, 2, 3, 4)
        assert ws["auth_mode"] in ("proxy", "oidc", "none")
        assert ws["gdpr_id"] == "app_demo"
        assert ws["traefik_router"] == "demo"

    def test_smoke_entry_uses_wider_expect(self, render, tmp_path):
        path = _write_app(tmp_path, "demo", _record())
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        se = app["smoke_entry"]
        assert se["id"] == "app_demo"
        assert 401 in se["expect"]   # accepts proxy-auth gate
        assert 502 in se["expect"]   # accepts Traefik-while-upstream-booting
        assert se["tier"] == 2

    def test_rbac_tier_default_and_clamp(self, render, tmp_path):
        # No nginx.rbac_tier in manifest → default 3
        path = _write_app(tmp_path, "demo", _record())
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert app["rbac_tier"] == 3

        # Explicit tier respected
        rec = _record()
        rec["nginx"] = {"auth": "proxy", "rbac_tier": 1}
        path2 = _write_app(tmp_path, "admin", rec)
        app2, _, _ = render._process_one(
            path2, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert app2["rbac_tier"] == 1

        # Out-of-range clamped
        rec3 = _record()
        rec3["nginx"] = {"auth": "proxy", "rbac_tier": 99}
        path3 = _write_app(tmp_path, "wild", rec3)
        app3, _, _ = render._process_one(
            path3, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert app3["rbac_tier"] == 4

    def test_kuma_monitor_inline_domain_marker(self, render, tmp_path):
        path = _write_app(tmp_path, "demo", _record())
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        km = app["kuma_monitor"]
        assert km["domain_var"] == "__inline__"
        assert km["_resolved_domain"] == "demo.apps.dev.local"
        assert km["install_flag"] == "__always__"


# ---------------------------------------------------------------------------
# Port resolution

class TestPortResolution(object):
    def test_meta_ports_wins(self, render, tmp_path):
        rec = _record(meta_overrides={"ports": [9999]})
        path = _write_app(tmp_path, "demo", rec)
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert app["registry_entry"]["port"] == 9999

    def test_fallback_to_compose_port_mapping(self, render, tmp_path):
        rec = _record(meta_overrides={"ports": []})
        path = _write_app(tmp_path, "demo", rec)
        app, _, _ = render._process_one(
            path, tenant_domain="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        # compose has "8080:8080"
        assert app["registry_entry"]["port"] == 8080
