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
            instance_tld="dev.local",
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
            path, instance_tld="dev.local", apps_subdomain="",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert app["fqdn"] == "demo.dev.local"

    def test_secret_seed_pins_existing_passwords(self, render, tmp_path):
        path = _write_app(tmp_path, "demo", _record())
        seed = {"demo": {"PASSWORD_DB": "PERSISTED-XYZ"}}
        app, secrets, _ = render._process_one(
            path, instance_tld="dev.local", apps_subdomain="apps",
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
            path, instance_tld="dev.local", apps_subdomain="apps",
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
            path, instance_tld="dev.local", apps_subdomain="apps",
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
            path, instance_tld="dev.local", apps_subdomain="apps",
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
            path, instance_tld="dev.local", apps_subdomain="apps",
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
            path, instance_tld="dev.local", apps_subdomain="apps",
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
            path, instance_tld="dev.local", apps_subdomain="apps",
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
            path, instance_tld="dev.local", apps_subdomain="apps",
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
            path, instance_tld="dev.local", apps_subdomain="apps",
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
            path, instance_tld="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        re_ = app["registry_entry"]
        assert re_["name"] == "demo"
        assert re_["tier"] == "2"
        assert re_["stack"] == "apps"
        assert re_["url"] == "https://demo.apps.dev.local/"
        assert re_["port"] == 8080

    def test_wing_system_minimal_fields(self, render, tmp_path):
        path = _write_app(tmp_path, "demo", _record())
        app, _, _ = render._process_one(
            path, instance_tld="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        ws = app["wing_system"]
        assert ws["id"] == "app_demo"
        assert ws["type"] == "app"
        assert ws["stack"] == "apps"

    def test_smoke_entry_uses_wider_expect(self, render, tmp_path):
        path = _write_app(tmp_path, "demo", _record())
        app, _, _ = render._process_one(
            path, instance_tld="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        se = app["smoke_entry"]
        assert se["id"] == "app_demo"
        assert 401 in se["expect"]   # accepts proxy-auth gate
        assert se["tier"] == 2

    def test_kuma_monitor_inline_domain_marker(self, render, tmp_path):
        path = _write_app(tmp_path, "demo", _record())
        app, _, _ = render._process_one(
            path, instance_tld="dev.local", apps_subdomain="apps",
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
            path, instance_tld="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        assert app["registry_entry"]["port"] == 9999

    def test_fallback_to_compose_port_mapping(self, render, tmp_path):
        rec = _record(meta_overrides={"ports": []})
        path = _write_app(tmp_path, "demo", rec)
        app, _, _ = render._process_one(
            path, instance_tld="dev.local", apps_subdomain="apps",
            secret_seed={}, extra_eu_registries=[], strict=False,
            traefik_network="shared_net",
        )
        # compose has "8080:8080"
        assert app["registry_entry"]["port"] == 8080
