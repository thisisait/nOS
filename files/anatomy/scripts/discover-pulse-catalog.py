#!/usr/bin/env python3
"""Discover Pulse job catalog from plugin manifests + agent profiles.

Plugin manifests carry Jinja-style placeholders like ``{{ playbook_dir }}``
and ``{{ global_password_prefix }}_pw_*`` in command/env strings. They're
authored as templates, not literals. Pulse stores the rendered command
in ``pulse_jobs.command`` and execs it directly at fire-time — no Jinja
engine inside the daemon. So we expand the placeholders BEFORE POSTing
to Wing; otherwise Pulse forks ``bash {{ playbook_dir }}/...`` which
exits 127 ("command not found"). Surfaced live 2026-05-07 when the
conductor self-test job auto-fired with rc=127.

This script lives as a standalone file (rather than inline-Python in a
shell heredoc inside post.yml) because Ansible Jinja-templates the
ENTIRE shell body before bash sees it — embedding Jinja tokens in a
heredoc breaks the Ansible argument splitter (failure class observed
2026-05-07 12:25 in ansible-playbook output: "failed at splitting
arguments, either an unbalanced jinja2 block or quotes"). Keeping the
substitutions table in plain Python with values pulled from env vars
sidesteps that whole interaction.

Inputs (env):
    NOS_PLAYBOOK_DIR             — repo root (substitutes {{ playbook_dir }})
    NOS_AUTHENTIK_DOMAIN         — full Authentik FQDN
    NOS_TENANT_DOMAIN            — operator's TLD
    NOS_GLOBAL_PASSWORD_PREFIX   — secret prefix
    NOS_WING_API_TOKEN           — Wing bearer for ansible-provisioned identity
    NOS_CONDUCTOR_WING_API_TOKEN — Wing bearer for nos-conductor identity
    NOS_BONE_SECRET              — HMAC secret (= WING_EVENTS_HMAC_SECRET)

Output (stdout):
    JSON list of {source, plugin_name, job} entries — directly consumable
    by the next post.yml task that POSTs each to /api/v1/pulse_jobs.
"""

from __future__ import annotations

import glob
import json
import os
import sys

import yaml


def _env(name: str, default: str = "") -> str:
    """Return an env var, falling back to default. Empty-string default
    keeps the substitution map total — missing env doesn't crash the
    discovery, it just leaves the original token in place (and the next
    role task will surface the failure with a clearer message)."""
    return os.environ.get(name, default)


def _build_substitutions() -> dict[str, str]:
    """Build the placeholder→value map from env vars set by Ansible.

    Keys are the LITERAL strings (with the Jinja braces) that appear in
    plugin.yml content — e.g. ``{{ playbook_dir }}`` is the literal
    11-character key. Python's ``str.replace`` does no Jinja parsing;
    these are just dumb substring substitutions.
    """
    return {
        "{{ playbook_dir }}":             _env("NOS_PLAYBOOK_DIR"),
        "{{ authentik_domain }}":         _env("NOS_AUTHENTIK_DOMAIN"),
        "{{ tenant_domain }}":            _env("NOS_TENANT_DOMAIN"),
        "{{ global_password_prefix }}":   _env("NOS_GLOBAL_PASSWORD_PREFIX"),
        "{{ wing_api_token }}":           _env("NOS_WING_API_TOKEN"),
        "{{ conductor_wing_api_token }}": _env("NOS_CONDUCTOR_WING_API_TOKEN"),
        "{{ bone_secret }}":              _env("NOS_BONE_SECRET"),
    }


def _expand(value, subs: dict[str, str]):
    """Recursively walk dict / list / str and apply substitutions."""
    if isinstance(value, str):
        for token, replacement in subs.items():
            if replacement:
                value = value.replace(token, replacement)
        return value
    if isinstance(value, dict):
        return {k: _expand(v, subs) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, subs) for v in value]
    return value


def _scan_sources(playbook_dir: str) -> list[str]:
    return (
        glob.glob(f"{playbook_dir}/files/anatomy/plugins/*/plugin.yml")
        + glob.glob(f"{playbook_dir}/files/anatomy/agents/*.yml")
    )


def main() -> int:
    playbook_dir = _env("NOS_PLAYBOOK_DIR")
    if not playbook_dir:
        print("error: NOS_PLAYBOOK_DIR not set", file=sys.stderr)
        return 2

    subs = _build_substitutions()
    catalog: list[dict] = []
    for path in _scan_sources(playbook_dir):
        try:
            with open(path) as fh:
                doc = yaml.safe_load(fh) or {}
        except Exception:
            continue
        block = doc.get("pulse") or {}
        for job in block.get("jobs") or []:
            catalog.append({
                "source": path.split("/anatomy/")[-1],
                "plugin_name": (
                    doc.get("name")
                    or doc.get("agent_id")
                    or path.split("/")[-1].replace(".yml", "")
                ),
                "job": _expand(job, subs),
            })

    print(json.dumps(catalog))
    return 0


if __name__ == "__main__":
    sys.exit(main())
