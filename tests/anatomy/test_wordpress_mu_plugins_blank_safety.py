"""Anatomy CI gate — WordPress mu-plugins blank-safety contract.

Pins (follow-up to commit 7f8541be, 2026-06-13):
  commit 7f8541be replaced per-FILE mu-plugin bind-mounts with a single
  DIRECTORY mount, because Docker cannot create single-file bind-mountpoints
  inside an external/virtiofs volume (wordpress_dir on /Volumes/...) on a fresh
  blank — it fails hard with "mountpoint ... is outside of rootfs" and the whole
  iiab stack-up dies. The existing tests (test_wordpress_rbac_mirror.py +
  test_devlog_wp_provisioning.py) spot-check individual mu-plugin files but never
  enumerate ALL source files nor pin the task ordering, so a developer adding a
  new mu-plugin .php WITHOUT a staging copy task would silently ship a feature
  that never loads (the .php sits in roles/.../files/ but is never bind-mounted).

This gate closes that gap:
  (1) every *.php in roles/pazny.wordpress/files/ has a copy task staging it into
      the mu-plugins staging dir (src renames are allowed — oidc-mu-plugin.php
      stages as oidc-bootstrap.php — so we match on `src: <file>`);
  (2) the staging directory is CREATED (ansible.builtin.file state=directory)
      BEFORE any copy targets it;
  (3) every staging copy runs BEFORE the compose-override render task (so the
      directory is fully populated at `docker compose up` time, not racing it);
  (4) the bind-mount is the single DIRECTORY mount form, never a per-file mount.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles/pazny.wordpress"
FILES = ROLE / "files"
MAIN = ROLE / "tasks/main.yml"
COMPOSE = ROLE / "templates/compose.yml.j2"

STAGING_DIR = "{{ stacks_dir }}/iiab/wordpress/mu-plugins"


def _tasks() -> list[dict]:
    return yaml.safe_load(MAIN.read_text(encoding="utf-8"))


def _php_sources() -> list[str]:
    return sorted(p.name for p in FILES.glob("*.php"))


def test_there_are_mu_plugin_sources():
    # Guard against the role's files/ dir being emptied/renamed out from under
    # the enumeration (which would make the per-file gate vacuously pass).
    srcs = _php_sources()
    assert srcs, "expected at least one *.php mu-plugin in roles/pazny.wordpress/files/"


def test_every_php_source_is_staged():
    tasks = _tasks()
    copy_srcs = {
        t["ansible.builtin.copy"]["src"]
        for t in tasks
        if isinstance(t, dict)
        and "ansible.builtin.copy" in t
        and STAGING_DIR in str(t["ansible.builtin.copy"].get("dest", ""))
    }
    for php in _php_sources():
        assert php in copy_srcs, (
            f"mu-plugin {php} has no copy task staging it to {STAGING_DIR} — a "
            "new mu-plugin must be staged or the directory mount never loads it"
        )


def test_staging_dir_created_before_copies():
    tasks = _tasks()
    mkdir_idx = None
    first_copy_idx = None
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            continue
        f = t.get("ansible.builtin.file")
        if (
            mkdir_idx is None
            and isinstance(f, dict)
            and f.get("state") == "directory"
            and str(f.get("path", "")) == STAGING_DIR
        ):
            mkdir_idx = i
        c = t.get("ansible.builtin.copy")
        if (
            first_copy_idx is None
            and isinstance(c, dict)
            and STAGING_DIR in str(c.get("dest", ""))
        ):
            first_copy_idx = i
    assert mkdir_idx is not None, "staging dir must be created via ansible.builtin.file state=directory"
    assert first_copy_idx is not None, "expected at least one staging copy task"
    assert mkdir_idx < first_copy_idx, "staging dir must be created BEFORE any mu-plugin is copied in"


def test_copies_run_before_compose_render():
    tasks = _tasks()
    last_copy_idx = None
    render_idx = None
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            continue
        c = t.get("ansible.builtin.copy")
        if isinstance(c, dict) and STAGING_DIR in str(c.get("dest", "")):
            last_copy_idx = i
        tpl = t.get("ansible.builtin.template")
        if (
            render_idx is None
            and isinstance(tpl, dict)
            and str(tpl.get("dest", "")).endswith("/iiab/overrides/wordpress.yml")
        ):
            render_idx = i
    assert last_copy_idx is not None, "expected staging copy tasks"
    assert render_idx is not None, "expected the compose-override render task"
    assert last_copy_idx < render_idx, (
        "all mu-plugins must be staged BEFORE the compose override is rendered so "
        "the directory is fully populated at compose-up time"
    )


def test_mount_is_single_directory_form():
    compose = COMPOSE.read_text(encoding="utf-8")
    assert f"{STAGING_DIR}:/var/www/html/wp-content/mu-plugins:ro" in compose, (
        "mu-plugins must be a single read-only DIRECTORY mount (the blank-safe form)"
    )
    # No per-file mountpoint may sneak back in — that is the regression 7f8541be
    # fixed (single-file bind-mounts → 'outside of rootfs' on virtiofs).
    per_file = re.search(r"mu-plugins/[\w.-]+\.php:", compose)
    assert per_file is None, f"per-file mu-plugin mount forbidden: {per_file.group(0) if per_file else ''}"
