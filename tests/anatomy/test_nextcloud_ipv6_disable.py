"""Anatomy gate — Nextcloud disables IPv6 in-container via sysctls.

Commit 33d63687 (2026-06-14) added IPv6-disable sysctls to the Nextcloud compose
fragment. The `auth.<tld>:host-gateway` extra_host (nextcloud-base plugin) resolves
to BOTH a working IPv4 (192.168.65.254) and a DEAD IPv6 (fdc4:..::254). user_oidc's
discovery fetch intermittently picks the IPv6 and fails → "Could not reach the
OpenID Connect provider" at login (the SSO redirect loop that survived a blank).

Without this gate a YAML reformat / template edit could silently drop the sysctl
block and re-open the intermittent OIDC failure. This pins:
  (1) the services.nextcloud block carries a sysctls map;
  (2) BOTH net.ipv6.conf.all.disable_ipv6 + net.ipv6.conf.default.disable_ipv6
      are present and equal the Docker-Compose string "1";
  (3) the template renders to valid Jinja2 + Docker-Compose YAML.

CI-safe: renders the template with stub vars; no Docker.
"""
from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = REPO / "roles/pazny.nextcloud/templates/compose.yml.j2"

# Minimal stub vars so the fragment renders to valid YAML without Ansible.
#
# `nextcloud_version` joined this list on 2026-08-06, when the template's
# `| default('stable')` was removed along with 60 other dead image fallbacks.
# The stub had been leaning on that fallback: without it the image line renders
# `image: nextcloud:` and the YAML parse fails with "mapping values are not
# allowed here". Production always supplies the pin, so the stub must too —
# a test that only passes because of a fallback is testing the fallback.
_STUB = {
    "nextcloud_version": "33",
    "nextcloud_dir": "/data/nextcloud",
    "nextcloud_data_dir": "/data/nextcloud-data",
    "nextcloud_db_name": "nextcloud",
    "nextcloud_db_user": "nextcloud",
    "nextcloud_db_password": "x",
    "nextcloud_admin_user": "admin",
    "nextcloud_admin_password": "x",
    "stacks_shared_network": "nos_shared",
}


def _render() -> str:
    try:
        from jinja2 import Environment
    except ImportError:  # pragma: no cover
        pytest.skip("jinja2 not available")
    env = Environment()
    return env.from_string(COMPOSE.read_text()).render(**_STUB)


def _nextcloud_block() -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        pytest.skip("pyyaml not available")
    doc = yaml.safe_load(_render())
    assert isinstance(doc, dict), "rendered fragment is not a YAML mapping"
    return doc["services"]["nextcloud"]


def test_sysctls_block_present():
    svc = _nextcloud_block()
    assert "sysctls" in svc, "Nextcloud compose must carry a sysctls block (IPv6 disable)"
    assert isinstance(svc["sysctls"], dict), "sysctls must be a YAML mapping"


def test_ipv6_disable_sysctls_set_to_string_one():
    sysctls = _nextcloud_block()["sysctls"]
    for key in ("net.ipv6.conf.all.disable_ipv6", "net.ipv6.conf.default.disable_ipv6"):
        assert key in sysctls, f"missing IPv6-disable sysctl: {key}"
        # Docker-Compose spec requires sysctl values as strings; "1" disables IPv6.
        assert sysctls[key] == "1", (
            f"{key} must equal the string \"1\" to disable IPv6 (got {sysctls[key]!r})"
        )


def test_template_is_valid_jinja2_and_yaml():
    # _render() raises on bad Jinja2; safe_load raises on bad YAML.
    block = _nextcloud_block()
    assert "image" in block, "rendered Nextcloud service block looks malformed"
