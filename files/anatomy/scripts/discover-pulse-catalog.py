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
        "{{ remediator_wing_api_token }}": _env("NOS_REMEDIATOR_WING_API_TOKEN"),
        "{{ scout_wing_api_token }}":      _env("NOS_SCOUT_WING_API_TOKEN"),
        "{{ upgrade_advisor_wing_api_token }}": _env("NOS_UPGRADE_ADVISOR_WING_API_TOKEN"),
        "{{ upgrade_architect_wing_api_token }}": _env("NOS_UPGRADE_ARCHITECT_WING_API_TOKEN"),
        "{{ migration_author_wing_api_token }}": _env("NOS_MIGRATION_AUTHOR_WING_API_TOKEN"),
        "{{ bone_secret }}":              _env("NOS_BONE_SECRET"),
        # A9.4-fixup (2026-05-17): wing-base dispatch jobs reference
        # {{ wing_home }} in env (WING_DB_PATH) and {{ wing_app_dir }}
        # in args[] (dispatch-notifications.php lives under app/bin/,
        # NOT ~/wing/bin/). Both substitutions populated from Ansible
        # at task time.
        "{{ wing_home }}":                _env("NOS_WING_HOME"),
        "{{ wing_app_dir }}":             _env("NOS_WING_APP_DIR"),
        # A9 mail/ntfy dispatch env (2026-05-26 fix): the catalog can't render
        # the conditional Jinja these used to carry, so wing post.yml now
        # Ansible-renders the resolved values (full var context) + passes them
        # as NOS_* env; wing-base/plugin.yml carries the matching bare tokens.
        "{{ ntfy_url }}":                 _env("NOS_NTFY_URL"),
        "{{ mail_host }}":                _env("NOS_MAIL_HOST"),
        "{{ mail_port }}":                _env("NOS_MAIL_PORT"),
        "{{ mail_tls_mode }}":            _env("NOS_MAIL_TLS_MODE"),
        "{{ mail_username }}":            _env("NOS_MAIL_USERNAME"),
        "{{ mail_password }}":            _env("NOS_MAIL_PASSWORD"),
        "{{ mail_tls_verify_flag }}":     _env("NOS_MAIL_TLS_VERIFY"),
        "{{ mail_from }}":                _env("NOS_MAIL_FROM"),
        "{{ mail_recipient }}":           _env("NOS_MAIL_RECIPIENT"),
        "{{ mail_digest_floor_val }}":    _env("NOS_MAIL_DIGEST_FLOOR"),
        "{{ mail_digest_cron }}":         _env("NOS_MAIL_DIGEST_CRON"),
        # keap-embed-sync (cortex Phase 6, 2026-07-11): keap-base/plugin.yml
        # carries these bare tokens; wing post.yml Ansible-renders the values.
        "{{ keap_port }}":                _env("NOS_KEAP_PORT"),
        "{{ keap_agent_token_rw }}":      _env("NOS_KEAP_AGENT_TOKEN_RW"),
        "{{ keap_agent_token_ro }}":      _env("NOS_KEAP_AGENT_TOKEN_RO"),
        "{{ librarian_wing_api_token }}": _env("NOS_LIBRARIAN_WING_API_TOKEN"),
        "{{ keap_agent_token_capture }}": _env("NOS_KEAP_AGENT_TOKEN_CAPTURE"),
        "{{ mariadb_root_password }}":    _env("NOS_MARIADB_ROOT_PASSWORD"),
        "{{ consolidate_fs_roots }}":     _env("NOS_CONSOLIDATE_FS_ROOTS"),
        "{{ consolidate_db_exclude }}":   _env("NOS_CONSOLIDATE_DB_EXCLUDE"),
    }


def _expand(value, subs: dict[str, str]):
    """Recursively walk dict / list / str and apply substitutions."""
    if isinstance(value, str):
        # Substitute every KNOWN token unconditionally — even when its value is
        # empty (e.g. NTFY_URL="" with install_ntfy off). The old `if replacement`
        # guard left empty-valued known tokens LITERAL, shipping "{{ … }}" into
        # pulse_jobs (the silent-failure class the conductor caught 2026-05-25).
        # Tokens not in `subs` are still untouched (stay literal — surfaced by
        # the bare-token guard test).
        for token, replacement in subs.items():
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
