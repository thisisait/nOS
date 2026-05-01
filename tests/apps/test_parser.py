"""Parser + GDPR-gate tests for module_utils/nos_app_parser.py.

The parser is the GDPR enforcement entry point — these tests are the
quality gate. If they pass, a Tier-2 app cannot deploy without a
complete Article 30 record.
"""

from __future__ import absolute_import, division, print_function

import os
import re

import pytest

from module_utils.nos_app_parser import (
    AppParseError,
    DEFAULT_EU_REGISTRIES,
    GDPR_LEGAL_BASES,
    SENSITIVE_DATA_SUBJECTS,
    gate_eu_residency,
    gate_sso_required,
    gate_tls_required,
    parse_app_file,
    resolve_tokens,
    validate,
)


# ---------------------------------------------------------------------------
# Helpers

def _valid_record(**overrides):
    base = {
        "meta": {"name": "demo", "version": "1.0", "summary": "demo app"},
        "gdpr": {
            "purpose": "demo processing",
            "legal_basis": "legitimate_interests",
            "data_categories": ["email"],
            "data_subjects": ["partners"],
            "retention_days": 90,
            "processors": [],
            "transfers_outside_eu": False,
        },
        "compose": {"services": {"app": {"image": "ghcr.io/demo/app:1"}}},
    }
    for k, v in overrides.items():
        if k == "gdpr" and isinstance(v, dict):
            base["gdpr"].update(v)
        else:
            base[k] = v
    return base


# ---------------------------------------------------------------------------
# Schema-level validation

class TestSchema(object):
    def test_missing_gdpr_block_is_the_first_error(self):
        rec = _valid_record()
        rec.pop("gdpr")
        with pytest.raises(AppParseError) as exc:
            validate(rec)
        # MANDATORY message must be the FIRST violation — operators see
        # it before any other noise.
        assert "MANDATORY" in exc.value.violations[0]
        assert "Article 30" in exc.value.violations[0]

    def test_missing_top_level_keys_are_collected(self):
        with pytest.raises(AppParseError) as exc:
            validate({"gdpr": _valid_record()["gdpr"]})
        joined = " ".join(exc.value.violations)
        assert "missing top-level key 'meta'" in joined
        assert "missing top-level key 'compose'" in joined

    def test_meta_name_must_be_lowercase_slug(self):
        rec = _valid_record(meta={"name": "BadName", "version": "1", "summary": "x"})
        with pytest.raises(AppParseError) as exc:
            validate(rec)
        assert any("meta.name" in v for v in exc.value.violations)

    @pytest.mark.parametrize("missing", [
        "purpose", "legal_basis", "data_categories", "data_subjects",
        "retention_days", "processors", "transfers_outside_eu",
    ])
    def test_each_gdpr_key_is_required(self, missing):
        rec = _valid_record()
        rec["gdpr"].pop(missing)
        with pytest.raises(AppParseError) as exc:
            validate(rec)
        assert any("gdpr.%s" % missing in v for v in exc.value.violations)

    def test_legal_basis_enum(self):
        rec = _valid_record(gdpr={"legal_basis": "vibes"})
        with pytest.raises(AppParseError) as exc:
            validate(rec)
        assert any("legal_basis" in v for v in exc.value.violations)

    @pytest.mark.parametrize("basis", GDPR_LEGAL_BASES)
    def test_every_documented_basis_validates(self, basis):
        rec = _valid_record(gdpr={"legal_basis": basis})
        validate(rec)  # no raise

    def test_retention_days_zero_rejected(self):
        rec = _valid_record(gdpr={"retention_days": 0})
        with pytest.raises(AppParseError) as exc:
            validate(rec)
        assert any("retention_days: 0" in v for v in exc.value.violations)

    def test_retention_days_negative_one_allowed(self):
        rec = _valid_record(gdpr={"retention_days": -1})
        validate(rec)

    def test_compose_services_required(self):
        rec = _valid_record()
        rec["compose"] = {"services": {}}
        with pytest.raises(AppParseError) as exc:
            validate(rec)
        assert any("compose.services" in v for v in exc.value.violations)


# ---------------------------------------------------------------------------
# Deploy gates

class TestGates(object):
    @pytest.mark.parametrize("subject", SENSITIVE_DATA_SUBJECTS)
    def test_tls_required_for_sensitive_subjects(self, subject):
        rec = _valid_record(gdpr={"data_subjects": [subject]})
        assert gate_tls_required(rec) is True

    def test_tls_not_required_for_partners_only(self):
        rec = _valid_record(gdpr={"data_subjects": ["partners"]})
        assert gate_tls_required(rec) is False

    def test_sso_required_when_consent(self):
        rec = _valid_record(gdpr={"legal_basis": "consent"})
        assert gate_sso_required(rec) is True

    def test_sso_not_required_for_other_bases(self):
        rec = _valid_record(gdpr={"legal_basis": "contract"})
        assert gate_sso_required(rec) is False

    def test_eu_residency_blocks_us_registries(self):
        rec = _valid_record(compose={"services": {
            "good": {"image": "ghcr.io/foo/bar:1"},
            "bad":  {"image": "gcr.io/foo/bar:1"},
        }})
        ok, off = gate_eu_residency(rec)
        assert ok is False
        assert any("gcr.io" in o for o in off)
        assert all("ghcr.io" not in o for o in off)

    def test_eu_residency_bypassed_when_acknowledged(self):
        rec = _valid_record(
            gdpr={"transfers_outside_eu": True},
            compose={"services": {"a": {"image": "gcr.io/x/y:1"}}},
        )
        ok, off = gate_eu_residency(rec)
        assert ok is True and off == []

    def test_eu_registry_default_implicit_docker_io(self):
        rec = _valid_record(compose={"services": {
            "a": {"image": "nginx:1.27-alpine"},  # no host = docker.io
        }})
        ok, _ = gate_eu_residency(rec)
        assert ok is True

    def test_unknown_registry_flagged_for_review(self):
        rec = _valid_record(compose={"services": {
            "a": {"image": "registry.weirdcorp.tld/x/y:1"},
        }})
        ok, off = gate_eu_residency(rec)
        assert ok is False
        assert any("not in allow-list" in o for o in off)

    def test_extra_eu_registries_extends_allow_list(self):
        rec = _valid_record(compose={"services": {
            "a": {"image": "registry.weirdcorp.tld/x/y:1"},
        }})
        ok, _ = gate_eu_residency(rec, extra_eu_registries=["registry.weirdcorp.tld"])
        assert ok is True

    def test_build_directive_is_skipped(self):
        # Operator-built images don't have an `image:` field — gate stays silent.
        rec = _valid_record(compose={"services": {
            "a": {"build": "./local"},
        }})
        ok, off = gate_eu_residency(rec)
        assert ok is True and off == []


# ---------------------------------------------------------------------------
# Magic-token resolver

class TestTokens(object):
    def test_fqdn_derived_from_app_name_suffix(self):
        out, _ = resolve_tokens(
            "https://$SERVICE_FQDN_IMMICH/", "immich", "dev.local",
        )
        assert "https://immich.dev.local/" == out

    def test_password_suffix_grouping(self):
        out, secrets = resolve_tokens(
            "$SERVICE_PASSWORD_DB / $SERVICE_PASSWORD_DB / $SERVICE_PASSWORD_OTHER",
            "demo", "dev.local",
        )
        a, b, c = out.split(" / ")
        assert a == b               # same suffix → identical value
        assert a != c               # different suffix → different value
        assert "PASSWORD_DB" in secrets and "PASSWORD_OTHER" in secrets

    def test_seed_pins_values(self):
        seed = {"PASSWORD_DB": "DEADBEEF"}
        out, _ = resolve_tokens(
            "$SERVICE_PASSWORD_DB", "demo", "dev.local", secret_seed=seed,
        )
        assert out == "DEADBEEF"

    def test_user_prefixed_with_app_name(self):
        out, _ = resolve_tokens(
            "$SERVICE_USER_DB", "immich", "dev.local",
        )
        assert out == "immich_db"

    def test_base64_lengths(self):
        import base64
        out, secrets_ = resolve_tokens(
            "$SERVICE_BASE64_32_K1 / $SERVICE_BASE64_64_K2", "x", "dev.local",
        )
        a, b = out.split(" / ")
        assert len(base64.b64decode(a)) == 32
        assert len(base64.b64decode(b)) == 64
        assert "BASE64_32_K1" in secrets_ and "BASE64_64_K2" in secrets_

    # ── Track F: host_alias + apps_subdomain segments ─────────────────────────
    # FQDN composition convention:
    #   $SERVICE_FQDN_<APP> -> <app>[.<host_alias>][.<apps_subdomain>].<tenant_domain>

    def test_fqdn_with_host_alias_only(self):
        """host_alias slots between app slug and tenant_domain (no subdomain)."""
        out, _ = resolve_tokens(
            "https://$SERVICE_FQDN_IMMICH/", "immich", "dev.local",
            host_alias="lab",
        )
        assert "https://immich.lab.dev.local/" == out

    def test_fqdn_with_apps_subdomain_only(self):
        """apps_subdomain slots between app slug and tenant_domain (Tier-2 default)."""
        out, _ = resolve_tokens(
            "https://$SERVICE_FQDN_DOCUMENSO/", "documenso", "dev.local",
            apps_subdomain="apps",
        )
        assert "https://documenso.apps.dev.local/" == out

    def test_fqdn_with_host_alias_and_apps_subdomain(self):
        """Both segments present: <app>.<host_alias>.<apps_subdomain>.<tenant_domain>."""
        out, _ = resolve_tokens(
            "https://$SERVICE_FQDN_DOCUMENSO/", "documenso", "dev.local",
            host_alias="lab", apps_subdomain="apps",
        )
        assert "https://documenso.lab.apps.dev.local/" == out

    def test_fqdn_empty_host_alias_byte_identical(self):
        """Empty host_alias drops the segment — backwards-compat with pre-Track-F."""
        out, _ = resolve_tokens(
            "https://$SERVICE_FQDN_IMMICH/", "immich", "dev.local",
            host_alias="",
        )
        assert "https://immich.dev.local/" == out


# ---------------------------------------------------------------------------
# Template file integration

def test_repo_template_parses_cleanly():
    here = os.path.dirname(os.path.abspath(__file__))
    template = os.path.abspath(os.path.join(here, "..", "..", "apps", "_template.yml"))
    record = parse_app_file(template)
    assert record["meta"]["name"] == "example"
    # Template's gates: legitimate_interests + end_users + transfers=false
    assert gate_tls_required(record) is True
    assert gate_sso_required(record) is False
    ok, off = gate_eu_residency(record)
    assert ok is True, off
