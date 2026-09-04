"""Anatomy gate — the four best-effort blueprints get a reader (fee 46).

main.yml's "Reapply authentik blueprints" loop applies six blueprints with
`|| true` + `failed_when: false` twice over — a blueprint that fails to apply is
INVISIBLE, the converge finishes green while the object was never created. The
estate rule is "success is written by a READER, not the attempting code."
`tasks/verify-authentik-apps.yml` read back ONLY the Applications
(10-oidc-apps); 20-rbac-policies, 30-agent-clients, 40-enrollment-flow and
46-brand-auth-flow could fail silently forever (roadmap
authentik-blueprint-readers, 2026-09-04).

This gate pins the reader's SHAPE by PARSING the task file as YAML (Ansible
task files are literal YAML with Jinja-in-strings — safe_load works; grepping
prose would be the antipattern plat-gate-shape just closed). It cannot prove
the objects exist in a running Authentik — that needs a live estate
(`--tags verify` against a real converge, or smoke). The object NAMES were
verified against the blueprint sources when the reader was written; the brand
check is presence-only until the serializer's read shape is confirmed live.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TASK_FILE = REPO / "tasks/verify-authentik-apps.yml"


def _tasks() -> list[dict]:
    return yaml.safe_load(TASK_FILE.read_text())


def _uri_urls() -> list[str]:
    urls = []
    for t in _tasks():
        uri = t.get("ansible.builtin.uri")
        if isinstance(uri, dict) and "url" in uri:
            urls.append(uri["url"])
    return urls


def _assert_names() -> list[str]:
    return [t["name"] for t in _tasks()
            if "ansible.builtin.assert" in t and "name" in t]


def test_reads_rbac_expression_policies():
    assert any("policies/expression/" in u for u in _uri_urls()), (
        "no read-back of the RBAC expression policies (20-rbac-policies)")


def test_reads_agent_oauth2_providers():
    assert any("providers/oauth2/" in u for u in _uri_urls()), (
        "no read-back of the agent OAuth2 providers (30-agent-clients)")


def test_reads_the_enrollment_flow():
    assert any("flows/instances/" in u for u in _uri_urls()), (
        "no read-back of the enrollment flow (40-enrollment-flow)")


def test_reads_the_default_brand():
    assert any("core/brands/" in u for u in _uri_urls()), (
        "no read-back of the default brand (46-brand-auth-flow)")


def test_asserts_exist_for_all_four_blueprints_plus_applications():
    names = _assert_names()
    for token, what in (("Application", "10-oidc-apps"),
                        ("RBAC tier", "20-rbac-policies"),
                        ("agent client", "30-agent-clients"),
                        ("enrollment flow", "40-enrollment-flow"),
                        ("default brand", "46-brand-auth-flow")):
        assert any(token in n for n in names), f"no assert for {what}"


def test_the_new_readbacks_are_not_gated_on_the_tofu_carveout():
    """OpenTofu owns only 10-oidc-apps; the other four apply under BOTH engines,
    so their read-backs must run under both — NOT behind `engine != tofu`. The
    Applications assert keeps that guard; the four new ones must not carry it."""
    for t in _tasks():
        if "ansible.builtin.assert" not in t:
            continue
        name = t.get("name", "")
        if any(k in name for k in ("RBAC tier", "agent client", "enrollment flow", "default brand")):
            when = " ".join(str(c) for c in (t.get("when") or []))
            assert "tofu" not in when, (
                f"{name!r} is gated on the tofu carve-out, but its blueprint "
                "applies under both engines — a tofu estate would skip the check")
