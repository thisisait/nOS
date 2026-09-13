"""Anatomy gate — Gitea Authentik OAuth source registers via CLI, loud verify.

THE TENDON. `tasks/stacks/authentik_service_post.yml` (Authentik→Gitea block)
is the live register path. The plugin hook
`files/anatomy/plugins/gitea-base/hooks/post_compose.yml` is the create-if-absent
mirror. `roles/pazny.gitea/tasks/post.yml` is the SSO-mandatory guard.

THE SAGA. Gitea has no REST endpoint for auth sources at any version. The
playbook POSTed `/api/v1/admin/identity-providers`, which 404'd behind
`failed_when: false` + `no_log`. The source never landed; with sso_autologin
hiding the local form that is LOCKOUT (`/user/oauth2/authentik` 500). Root-
caused 2026-06-13. Canonical path: `gitea admin auth add-oauth` /
`update-oauth --id`, idempotency keyed off `gitea admin auth list`.

This gate freezes that fix so T32.2 cannot quietly re-invent GitLab as the
agent forge "because Gitea SSO is broken". LIVE SSO on a running estate is
UNVERIFIED here — this is a source-shape pin, not a converge.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
POST = REPO / "tasks/stacks/authentik_service_post.yml"
HOOK = REPO / "files/anatomy/plugins/gitea-base/hooks/post_compose.yml"
ROLE_POST = REPO / "roles/pazny.gitea/tasks/post.yml"


def _tasks() -> list[dict]:
    docs = yaml.safe_load(POST.read_text(encoding="utf-8"))
    assert isinstance(docs, list), "authentik_service_post.yml must be a task list"
    return [t for t in docs if isinstance(t, dict)]


def _gitea_tasks() -> list[dict]:
    return [t for t in _tasks() if str(t.get("name", "")).startswith("[Authentik->Gitea]")]


def _argv(task: dict) -> list[str]:
    cmd = task.get("ansible.builtin.command") or {}
    if isinstance(cmd, dict):
        return [str(x) for x in (cmd.get("argv") or [])]
    return []


def test_live_path_uses_cli_not_phantom_rest():
    block = "\n".join(str(t) for t in _gitea_tasks())
    assert "identity-providers" not in block, (
        "the Gitea OAuth register still talks to /api/v1/admin/identity-providers "
        "— that path exists at no Gitea version; it is the SSO lockout"
    )
    create = [t for t in _gitea_tasks() if "add-oauth" in _argv(t)]
    rotate = [t for t in _gitea_tasks() if "update-oauth" in _argv(t)]
    assert create, "create task must call gitea admin auth add-oauth"
    assert rotate, "rotate task must call gitea admin auth update-oauth"


def test_create_if_absent_and_rotate_split():
    create = next(t for t in _gitea_tasks() if "add-oauth" in _argv(t))
    rotate = next(t for t in _gitea_tasks() if "update-oauth" in _argv(t))
    when_c = str(create.get("when"))
    when_r = str(rotate.get("when"))
    assert "== ''" in when_c or '== ""' in when_c, (
        "add-oauth must be gated on an empty resolved source id"
    )
    assert "!= ''" in when_r or '!= ""' in when_r, (
        "update-oauth must be gated on a non-empty source id"
    )
    assert create.get("no_log") is True
    assert rotate.get("no_log") is True
    assert create.get("failed_when") is False
    assert rotate.get("failed_when") is False


def test_verify_is_loud():
    verify = next(
        t for t in _gitea_tasks()
        if "Verify" in str(t.get("name", ""))
    )
    failed = str(verify.get("failed_when"))
    assert verify.get("failed_when") is not False
    assert "authentik" in failed and "_gitea_oauth_verify.stdout" in failed
    cmd = verify.get("ansible.builtin.command", "")
    assert "admin auth list" in str(cmd)


def test_create_maps_tier1_admin_group():
    create = next(t for t in _gitea_tasks() if "add-oauth" in _argv(t))
    argv = _argv(create)
    assert "--group-claim-name" in argv and "groups" in argv
    assert "--admin-group" in argv
    joined = " ".join(argv)
    assert "selectattr('tier', 'equalto', 1)" in joined


def test_every_gitea_cli_exec_runs_as_git():
    for t in _gitea_tasks():
        blob = str(t)
        if "compose" in blob and "gitea" in blob:
            argv = _argv(t)
            if argv:
                assert "-u" in argv and "git" in argv, t.get("name")
            else:
                assert "-u git" in blob, t.get("name")


def test_plugin_hook_mirrors_cli_create():
    hook = HOOK.read_text(encoding="utf-8")
    assert "add-oauth" in hook
    assert "path: /api/v1/admin/identity-providers" not in hook
    assert "--group-claim-name" in hook
    assert "selectattr('tier', 'equalto', 1)" in hook


def test_role_sso_guard_refuses_hidden_form_without_source():
    text = ROLE_POST.read_text(encoding="utf-8")
    assert "admin auth list" in text
    assert "LOCKOUT" in text
    assert "path: /api/v1/admin/identity-providers" not in text
    assert "'authentik' not in" in text
