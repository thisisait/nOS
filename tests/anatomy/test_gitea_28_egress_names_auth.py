"""Gitea 28 moved egress to one [security] ALLOWED_HOST_LIST (go-gitea#39426).

It governs webhooks AND OAuth2 clients; in the default lax mode every
non-public host that is not listed is denied. auth.<tld> is mapped to
host-gateway (a private address), so a 28 render that keeps only the old
[webhook] key denies the Authentik token exchange: SSO lockout. Below 28
the old key must stay (the pin is 1.27.x until upgrades/gitea.yml is proven).
Renders the real template — not a grep of its text.
"""
from __future__ import annotations

from pathlib import Path

import jinja2
import yaml
from ansible.plugins.filter.core import to_bool
from ansible.plugins.test.core import version_compare

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "roles/pazny.gitea/templates/compose.yml.j2"


def _env(version: str, authentik: bool) -> dict:
    env = jinja2.Environment(trim_blocks=True)
    env.tests["version"] = version_compare
    env.filters["bool"] = to_bool
    text = env.from_string(TEMPLATE.read_text()).render(
        gitea_version=version,
        install_authentik=authentik,
        tenant_domain="dev.local",
        woodpecker_domain="ci.dev.local",
        authentik_domain="auth.dev.local",
        stacks_dir="/tmp/stacks",
        stacks_shared_network="shared_net",
        ansible_facts={"user_uid": 501, "user_gid": 20, "env": {"HOME": "/h"}},
        nos_derived_secrets={"gitea_secret": "s", "gitea_metrics": "m"},
    )
    return yaml.safe_load(text)["services"]["gitea"]["environment"]


def test_28_names_ci_and_auth_in_security_list() -> None:
    env = _env("28.1.0", authentik=True)
    assert env["GITEA__security__ALLOWED_HOST_LIST"] == "ci.dev.local,auth.dev.local"
    assert "GITEA__webhook__ALLOWED_HOST_LIST" not in env


def test_28_without_authentik_names_only_ci() -> None:
    env = _env("28.1.0", authentik=False)
    assert env["GITEA__security__ALLOWED_HOST_LIST"] == "ci.dev.local"


def test_1_27_keeps_the_webhook_key() -> None:
    env = _env("1.27.3", authentik=True)
    assert env["GITEA__webhook__ALLOWED_HOST_LIST"] == "ci.dev.local"
    assert "GITEA__security__ALLOWED_HOST_LIST" not in env
