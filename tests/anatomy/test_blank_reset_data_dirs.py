"""Anatomy CI gate — blank-reset must wipe every Docker bind-mount data dir.

tasks/removal-set.yml builds `_blank_dirs` (a set_fact) from ~50 conditional
ternary clauses, each `(install_<svc> | default(false)) | ternary([<dir>...], [])`.
Each clause maps an `install_*` feature flag to the host directories that the
matching service bind-mounts into its container.

A service that bind-mounts a host directory (e.g. `~/snappymail:/snappymail/data`)
is NOT cleaned by the `docker volume prune` step earlier in blank-reset.yml —
prune only removes named/anonymous Docker volumes, never host bind-mount paths.
So if such a service has an `install_*` flag + a `*_data_dir` default but no
clause in `_blank_dirs`, then `blank=true` orphans the old directory: the next
blank inherits stale data → cross-run data leakage / config inconsistency.

This gate:
  1. Asserts the `_blank_dirs` set_fact exists and is Jinja-parseable (the ternary
     soup stays syntactically sound).
  2. Extracts the set of `install_*` flags referenced inside `_blank_dirs`.
  3. Asserts every Docker-service flag that owns a persistent host bind-mount data
     dir (the REQUIRED contract below) is present in `_blank_dirs`.
  4. Verifies external-paths.yml is included BEFORE `_blank_dirs` is built, so
     `external_storage_root` overrides are visible to the wipe list.

The gate auto-fails when a new bind-mount service is added to default.config.yml
with an `install_*` flag + data dir but is not wired into `_blank_dirs`.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
REMOVAL_SET_PATH = REPO_ROOT / "tasks" / "removal-set.yml"
BLANK_RESET_PATH = REPO_ROOT / "tasks" / "blank-reset.yml"

# ── REQUIRED contract ────────────────────────────────────────────────────
# install_<svc> flags whose service bind-mounts a PERSISTENT HOST directory
# (volumes: - <host_dir>:<container_path> in the role compose template).
# Each MUST appear in the _blank_dirs ternary soup or its data orphans on blank.
#
# Excluded by design (documented, NOT a gap):
#   - install_erpnext   → erpnext_data_dir DEPRECATED since P0.1 (named volume,
#                         cleaned by `docker volume prune -f -a`).
#   - install_miniflux  → stateless container, state lives in PostgreSQL.
#   - install_iiab_terminal → host config under {{ homebrew_prefix }}/etc, kept
#                         alongside Homebrew packages per blank doctrine.
REQUIRED_BIND_MOUNT_FLAGS = {
    "install_wordpress",
    "install_nextcloud",
    "install_n8n",
    "install_kiwix",
    "install_gitea",
    "install_gitlab",
    "install_jellyfin",
    "install_openwebui",
    "install_uptime_kuma",
    "install_portainer",
    "install_woodpecker",
    "install_calibreweb",
    "install_homeassistant",
    "install_rustfs",
    "install_freescout",
    "install_outline",
    "install_metabase",
    "install_superset",
    "install_bluesky_pds",
    "install_paperclip",
    "install_authentik",
    "install_infisical",
    "install_vaultwarden",
    "install_ntfy",
    "install_nodered",
    "install_influxdb",
    "install_code_server",
    "install_bookstack",
    "install_firefly",
    "install_hedgedoc",
    "install_onlyoffice",
    "install_mcp_gateway",
    "install_snappymail",
    "install_spacetimedb",
    # KEAP /data is DERIVED (libsql mirror) — blank wipes it so KEAP re-syncs
    # from the PRESERVED user-file source (blank=preserve-source split, 2026-07-19).
    # Was an unguarded gap: keap had a data_dir but no _blank_dirs clause, so a
    # blank left KEAP re-mirroring stale data. See blank-uninstall-managed-resources.md.
    "install_keap",
}


def _extract_blank_dirs_expr() -> str:
    """Return the raw Jinja expression body of the _blank_dirs set_fact.

    Matches `_blank_dirs: >-` and captures the indented multi-line block that
    follows, up to the next less-indented YAML key.
    """
    src = REMOVAL_SET_PATH.read_text()
    match = re.search(
        r"\n    _blank_dirs:\s*>-\n(?P<body>(?:(?: {6,}.*)?\n)+)",
        src,
    )
    assert match, "could not locate the `_blank_dirs: >-` set_fact block"
    return match.group("body")


def _plays(path):
    return yaml.safe_load(path.read_text()) or []


def test_blank_dirs_set_fact_exists():
    """Parsed, not grepped: a comment naming `_blank_dirs` satisfied the old
    text assert, so the wipe could vanish with the gate still green."""
    assert any(
        "_blank_dirs" in (t.get("ansible.builtin.set_fact") or t.get("set_fact") or {})
        for t in _plays(REMOVAL_SET_PATH)
    ), "_blank_dirs set_fact missing from removal-set.yml"
    assert [
        t for t in _plays(BLANK_RESET_PATH)
        if t.get("loop") == "{{ _blank_dirs }}"
        and (t.get("ansible.builtin.file") or t.get("file") or {}).get("state") == "absent"
    ], "no task removes the paths in _blank_dirs — a blank would leave the data dirs"


def test_blank_dirs_expression_is_jinja_parseable():
    """The ternary soup must stay syntactically sound (no broken edit)."""
    jinja2 = pytest.importorskip("jinja2")
    # The folded-scalar body is already a complete `{{ ... }}` Jinja expression;
    # parse it as-is so Jinja validates the full ternary-soup grammar.
    body = _extract_blank_dirs_expr()
    assert body.lstrip().startswith("{{") and body.rstrip().endswith("}}"), (
        "_blank_dirs body is not a self-contained {{ ... }} expression"
    )
    try:
        jinja2.Environment().parse(body)
    except jinja2.TemplateSyntaxError as exc:  # pragma: no cover - failure path
        pytest.fail(f"_blank_dirs Jinja expression is not parseable: {exc}")


def test_every_bind_mount_service_is_wiped():
    """Core gate: each REQUIRED bind-mount flag must appear in _blank_dirs.

    A missing flag means that service's host directory orphans on blank=true.
    """
    body = _extract_blank_dirs_expr()
    referenced = set(re.findall(r"install_[a-z0-9_]+", body))

    missing = sorted(REQUIRED_BIND_MOUNT_FLAGS - referenced)
    if missing:
        pytest.fail(
            "tasks/removal-set.yml `_blank_dirs` is missing a wipe clause for "
            "these bind-mount services (their host data dir orphans on blank=true):"
            "\n  - " + "\n  - ".join(missing)
            + "\n\nAdd a `(<flag> | default(false)) | ternary([<dir>...], [])` "
            "clause for each in the _blank_dirs set_fact."
        )


def test_external_paths_included_before_blank_dirs():
    """external-paths.yml must run BEFORE _blank_dirs so storage overrides apply.

    external_storage_root rewrites *_data_dir to /Volumes/... If the include ran
    after the set_fact, blank would wipe the empty ~/service fallbacks and leave
    the real external data behind.
    """
    src = REMOVAL_SET_PATH.read_text()
    ext_idx = src.find("stacks/external-paths.yml")
    blank_idx = src.find("_blank_dirs:")
    assert ext_idx != -1, "external-paths.yml include missing from removal-set.yml"
    assert blank_idx != -1, "_blank_dirs set_fact missing"
    assert ext_idx < blank_idx, (
        "external-paths.yml must be included BEFORE _blank_dirs is built so "
        "external_storage_root overrides are visible to the wipe list"
    )
