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

    THE SECRET-SHAPED ENTRIES EMIT A REFERENCE, NOT A VALUE (2026-08-11).
    `"{{ wing_api_token }}": "secret:wing_api_token"` puts a POINTER into
    `pulse_jobs.env_json`; `pulse/daemon.py::_resolve_secrets` reads the real
    value from ~/.nos/secrets.yml (0600) at exec time and fails the job if the
    name is not there. Before this, 19 of 29 job rows held a derived secret in
    the clear in wing.db — a file the /audit timeline, the events API and the
    nightly backup all reach, and one row of which also reveals the prefix that
    yields the rest by construction.

    `{{ global_password_prefix }}` deliberately stays a VALUE: manifests
    concatenate it (`{{ global_password_prefix }}_pw_agent_curator`), so a
    reference would render as `secret:global_password_prefix_pw_agent_curator`
    — a name that does not exist, failing the job at exec time instead of at
    render. Those sites need a named var of their own; until then they are the
    measured remainder, not a thing this change quietly covers.
    """
    return {
        "{{ playbook_dir }}":             _env("NOS_PLAYBOOK_DIR"),
        # The agent client secrets, keyed on the WHOLE literal rather than on
        # `{{ global_password_prefix }}` alone. Substituting the prefix would
        # render `secret:global_password_prefix_pw_agent_curator` — a name that
        # does not exist — so the concatenation is matched entire and replaced
        # by a reference to the name the store now carries. These MUST precede
        # the bare-prefix entry below: str.replace runs in dict order and the
        # shorter key would consume the prefix first, leaving a broken tail.
        "{{ global_password_prefix }}_pw_agent_conductor": "secret:agent_conductor_client_secret",
        "{{ global_password_prefix }}_pw_agent_curator": "secret:agent_curator_client_secret",
        "{{ global_password_prefix }}_pw_agent_librarian": "secret:agent_librarian_client_secret",
        "{{ global_password_prefix }}_pw_agent_migration_author": "secret:agent_migration_author_client_secret",
        "{{ global_password_prefix }}_pw_agent_remediator": "secret:agent_remediator_client_secret",
        "{{ global_password_prefix }}_pw_agent_scout": "secret:agent_scout_client_secret",
        "{{ global_password_prefix }}_pw_agent_upgrade_architect": "secret:agent_upgrade_architect_client_secret",
        "{{ global_password_prefix }}_pw_agent_upgrade_advisor": "secret:agent_upgrade_advisor_client_secret",
        "{{ global_password_prefix }}_pw_agent_inspektor": "secret:agent_inspektor_client_secret",
        "{{ authentik_domain }}":         _env("NOS_AUTHENTIK_DOMAIN"),
        "{{ tenant_domain }}":            _env("NOS_TENANT_DOMAIN"),
        "{{ global_password_prefix }}":   _env("NOS_GLOBAL_PASSWORD_PREFIX"),
        "{{ wing_api_token }}":           "secret:wing_api_token",
        "{{ conductor_wing_api_token }}": "secret:conductor_wing_api_token",
        "{{ remediator_wing_api_token }}": "secret:remediator_wing_api_token",
        "{{ scout_wing_api_token }}":      "secret:scout_wing_api_token",
        "{{ upgrade_advisor_wing_api_token }}": "secret:upgrade_advisor_wing_api_token",
        "{{ upgrade_architect_wing_api_token }}": "secret:upgrade_architect_wing_api_token",
        "{{ migration_author_wing_api_token }}": "secret:migration_author_wing_api_token",
        "{{ bone_secret }}":              "secret:bone_secret",
        # The audit chain's retired-key ring (2026-08-06). Verify-only, and
        # legitimately EMPTY until the first rotation. A REFERENCE since
        # 2026-08-12: this was the one secret-shaped token still substituted as
        # a VALUE — it escaped the 2026-08-11 sweep because it is not
        # `_pw_`-shaped — so the live `audit-chain-verify` row carried the
        # retired chain key as a 64-hex literal in env_json. That key is the
        # LEAKED one (the reason it was rotated out); anything that could read
        # wing.db could still VERIFY — and therefore forge — chain segments
        # from its era. The store declares `bone_secret_retired` even when
        # empty (templates/secrets.yml.j2), and the daemon resolves
        # declared-and-empty as an answer, so the reference is blank-safe.
        "{{ bone_secret_retired }}":      "secret:bone_secret_retired",
        # Bone's port, so a manifest need not hardcode 8099 (the gitleaks
        # notification hardcoded 9000 — Wing's — and 401ed nightly).
        "{{ bone_port }}":                _env("NOS_BONE_PORT"),
        # alert-relay-base (2026-08-05) polls Prometheus for firing alerts.
        "{{ prometheus_port }}":          _env("NOS_PROMETHEUS_PORT"),
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
        # 2026-08-08: the dispatcher used to publish ANONYMOUSLY, which worked
        # only because ntfy's auth was unconfigured (no auth-file, so the
        # declared deny-all was inert and anyone could also SUBSCRIBE).
        "{{ ntfy_publisher_user }}":      _env("NOS_NTFY_PUBLISH_USER"),
        "{{ ntfy_publisher_password }}":  "secret:ntfy_publisher_password",
        "{{ mail_host }}":                _env("NOS_MAIL_HOST"),
        "{{ mail_port }}":                _env("NOS_MAIL_PORT"),
        "{{ mail_tls_mode }}":            _env("NOS_MAIL_TLS_MODE"),
        "{{ mail_username }}":            _env("NOS_MAIL_USERNAME"),
        "{{ mail_password }}":            "secret:mail_password",
        "{{ mail_tls_verify_flag }}":     _env("NOS_MAIL_TLS_VERIFY"),
        "{{ mail_from }}":                _env("NOS_MAIL_FROM"),
        "{{ mail_recipient }}":           _env("NOS_MAIL_RECIPIENT"),
        "{{ mail_digest_floor_val }}":    _env("NOS_MAIL_DIGEST_FLOOR"),
        "{{ mail_digest_cron }}":         _env("NOS_MAIL_DIGEST_CRON"),
        # keap-embed-sync (cortex Phase 6, 2026-07-11): keap-base/plugin.yml
        # carries these bare tokens; wing post.yml Ansible-renders the values.
        "{{ keap_port }}":                _env("NOS_KEAP_PORT"),
        "{{ keap_agent_token_rw }}":      "secret:keap_agent_token_rw",
        "{{ keap_agent_token_ro }}":      "secret:keap_agent_token_ro",
        "{{ librarian_wing_api_token }}": "secret:librarian_wing_api_token",
        # curator-sweep shipped 2026-07-14 with this token in its env and no
        # entry here, so Pulse stored the literal braces as the bearer. env is
        # not covered by the SEC-8 command validator, so it never 400'd — the
        # agent would simply have 401'd against Wing at run time, silently.
        # Found 2026-08-01 by test_pulse_catalog_renders_every_token.
        "{{ curator_wing_api_token }}":   "secret:curator_wing_api_token",
        "{{ keap_agent_token_capture }}": "secret:keap_agent_token_capture",
        "{{ mariadb_root_password }}":    "secret:mariadb_root_password",
        # backup-restore-drill (2026-08-01): the weekly DR round-trip.
        "{{ backup_verify_script_path }}": _env("NOS_BACKUP_VERIFY_SCRIPT"),
        "{{ consolidate_fs_roots }}":     _env("NOS_CONSOLIDATE_FS_ROOTS"),
        "{{ consolidate_db_exclude }}":   _env("NOS_CONSOLIDATE_DB_EXCLUDE"),
        # S2 corpus-in-parallel (docs/archive/cortex-corpus-parallel.md): the two
        # keap-base feeders FAN OUT to the cortex organ, and cortex-base adds the
        # agreement harness. The URL is Ansible-rendered to "" when the organ is
        # not installed, which is what makes the fan-out degrade to exactly the
        # single-target job it was. The tokens are DISTINCT names holding DISTINCT
        # secrets from KEAP's — one name, two secrets, one host is how a write
        # token reaches the wrong daemon (§2.1).
        "{{ cortex_fanout_url }}":        _env("NOS_CORTEX_FANOUT_URL"),
        "{{ cortex_rw_token }}":          "secret:cortex_rw_token",
        "{{ cortex_ro_token }}":          "secret:cortex_ro_token",
        "{{ cortex_capture_token }}":     "secret:cortex_capture_token",
        # MiniMax (PREPARED, NOT ARMED). The token → a `secret:` reference so
        # the key never rides as a value. Present in the map unconditionally so
        # test_pulse_catalog_renders_every_token is satisfied the day a manifest
        # first uses it; the ENV that carries it is injected only when armed
        # (_minimax_env below). See docs/minimax-groundwork.md.
        "{{ minimax_api_key }}":         "secret:minimax_api_key",
    }


def _minimax_env() -> dict[str, str]:
    """The Anthropic-compatible backend override, or {} when not armed.

    PREPARED, NOT ARMED. Injected into every scheduled agent job ONLY when
    NOS_MINIMAX_ENABLED is truthy (Ansible renders it from minimax_enabled,
    default false). Off → {} → nothing changes and the feature is inert.

    Shape (the "already verified" env contract): ANTHROPIC_BASE_URL is a plain
    value; ANTHROPIC_AUTH_TOKEN is a `secret:` reference the Pulse daemon
    resolves at exec time; the two ANTHROPIC_*_MODEL keys remap the haiku/sonnet/
    opus aliases the jobs pin onto MiniMax model ids. _safe_env in
    pulse/runners/subprocess.py lets all four through (none match the ban regex).
    """
    if _env("NOS_MINIMAX_ENABLED").strip().lower() not in ("1", "true", "yes"):
        return {}
    env = {
        "ANTHROPIC_BASE_URL": _env("NOS_MINIMAX_BASE_URL"),
        "ANTHROPIC_AUTH_TOKEN": "secret:minimax_api_key",
    }
    # Alias remaps are optional — only emit a key when the operator set its id,
    # so an unarmed-but-enabled misconfig doesn't blank the model to "".
    if _env("NOS_MINIMAX_MODEL"):
        env["ANTHROPIC_MODEL"] = _env("NOS_MINIMAX_MODEL")
    if _env("NOS_MINIMAX_SMALL_MODEL"):
        env["ANTHROPIC_SMALL_FAST_MODEL"] = _env("NOS_MINIMAX_SMALL_MODEL")
    return env


# Jobs that run a scheduled agent — the only ones the MiniMax backend applies to.
_AGENT_RUNNER = "pulse-run-agent.sh"


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
    minimax_env = _minimax_env()   # {} unless armed — computed once
    catalog: list[dict] = []
    for path in _scan_sources(playbook_dir):
        try:
            with open(path) as fh:
                doc = yaml.safe_load(fh) or {}
        except Exception:
            continue
        block = doc.get("pulse") or {}
        for job in block.get("jobs") or []:
            expanded = _expand(job, subs)
            # PREPARED, NOT ARMED: when minimax is enabled, the backend override
            # rides on every scheduled-agent job. A job's OWN env wins on a key
            # clash (it is more specific), so this only ADDS the ANTHROPIC_* keys.
            if minimax_env and _AGENT_RUNNER in str(expanded.get("command", "")):
                merged = dict(minimax_env)
                merged.update(expanded.get("env") or {})
                expanded["env"] = merged
            catalog.append({
                "source": path.split("/anatomy/")[-1],
                "plugin_name": (
                    doc.get("name")
                    or doc.get("agent_id")
                    or path.split("/")[-1].replace(".yml", "")
                ),
                "job": expanded,
            })

    print(json.dumps(catalog))
    return 0


if __name__ == "__main__":
    sys.exit(main())
