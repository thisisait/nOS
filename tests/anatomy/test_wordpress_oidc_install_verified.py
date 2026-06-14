"""Anatomy CI gate — WordPress OIDC plugin install must be VERIFIED.

Pins (SSO completeness audit, sso-wordpress-oidc-plugin-install-silent):
  - The role install task carries failed_when:false (idempotent re-run), which
    masks a wp.org API timeout / 404. Without a subsequent verify, the post task
    reports success, the mu-plugin renders a broken config against a missing
    plugin, and the operator hits a 404 on the Authentik redirect.
  - So a LOUD verify task MUST run `wp plugin is-active
    daggerhart-openid-connect-generic --allow-root` WITHOUT failed_when, gated
    on install_authentik + container-running.
  - The wordpress-base plugin loader hook mirrors a verify step that re-checks
    is-active (no accept_substring escape hatch) so a silent install failure
    surfaces in the replay summary.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
POST_TASKS = REPO / "roles/pazny.wordpress/tasks/post.yml"
HOOK = REPO / "files/anatomy/plugins/wordpress-base/hooks/post_compose.yml"

PLUGIN_SLUG = "daggerhart-openid-connect-generic"


def _tasks() -> list[dict]:
    return yaml.safe_load(POST_TASKS.read_text(encoding="utf-8"))


def _shell(task: dict) -> str:
    return str(task.get("ansible.builtin.shell", ""))


def test_role_has_loud_oidc_verify_task():
    tasks = _tasks()
    verify = [
        t for t in tasks
        if f"wp plugin is-active {PLUGIN_SLUG}" in _shell(t)
        and "failed_when" not in t  # the LOUD one — no escape hatch
    ]
    assert verify, (
        "post.yml must have a verify task running "
        f"`wp plugin is-active {PLUGIN_SLUG}` WITHOUT failed_when"
    )


def test_oidc_verify_is_authentik_and_container_gated():
    tasks = _tasks()
    verify = next(
        t for t in tasks
        if f"wp plugin is-active {PLUGIN_SLUG}" in _shell(t)
        and "failed_when" not in t
    )
    when = " ".join(str(c) for c in (verify.get("when") or []))
    assert "install_authentik" in when, "verify must be gated on install_authentik"
    assert "_wp_container.stdout" in when, "verify must be gated on container running"
    # A bare is-active check has nothing to converge — must not be changed=true.
    assert verify.get("changed_when") is False, "verify is a probe, not a change"


def test_verify_runs_even_when_install_skipped():
    """The verify must NOT depend on _wp_oidc_active.rc != 0 — otherwise a plugin
    that silently dropped to inactive between runs (or a prior masked failure)
    would skip the verify exactly when it's needed."""
    tasks = _tasks()
    verify = next(
        t for t in tasks
        if f"wp plugin is-active {PLUGIN_SLUG}" in _shell(t)
        and "failed_when" not in t
    )
    when = " ".join(str(c) for c in (verify.get("when") or []))
    assert "_wp_oidc_active.rc" not in when, (
        "verify must run regardless of whether install was attempted"
    )


def test_install_task_still_idempotent_failsafe():
    """The install task keeps failed_when:false (re-run idempotence). The gate is
    the SEPARATE verify task — this pins that the two are distinct."""
    tasks = _tasks()
    install = [
        t for t in tasks
        if f"wp plugin install {PLUGIN_SLUG}" in _shell(t)
    ]
    assert install, "install task must exist"
    assert install[0].get("failed_when") is False, (
        "install stays failed_when:false; the verify task is the gate"
    )


def test_hook_mirrors_verify_step():
    doc = yaml.safe_load(HOOK.read_text(encoding="utf-8"))
    seq = doc["sequence"]
    verify = [
        s for s in seq
        if s.get("runner") == "docker_exec"
        and f"wp plugin is-active {PLUGIN_SLUG}" in str(s.get("cmd", ""))
    ]
    assert verify, "post_compose hook must mirror a verify is-active step"
    step = verify[0]
    assert "accept_substring_in_stdout" not in step, (
        "verify step must NOT carry an accept_substring escape hatch"
    )
    assert "install_authentik" in str(step.get("when", "")), (
        "hook verify must be gated on install_authentik"
    )
