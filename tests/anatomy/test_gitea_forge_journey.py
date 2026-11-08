"""One journey through Gitea as the estate's forge: the role's compose render and
post-start provisioning, its SSO lockout guard, and the trunk sync and forge choice
that make Gitea primary and GitLab an optional replacement.

Absorbed (2026-11-08, roadmap gate-diet-role-journeys), one section each:
  test_gitea_admin_provisioning, test_gitea_sso_guard_knows_the_run_shape,
  test_gitea_28_egress_names_auth, test_gitea_forge_sync_not_mirror,
  test_forge_gitlab_is_optional.
Every assert of those files survives here with the same inputs and expectations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import jinja2
import pytest
import yaml
from ansible.plugins.filter.core import to_bool
from ansible.plugins.test.core import version_compare

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

POST = REPO / "roles/pazny.gitea/tasks/post.yml"
TEMPLATE = REPO / "roles/pazny.gitea/templates/compose.yml.j2"
NOS_PUSH = REPO / "tools" / "nos-push"
SYNC_GL = REPO / "tools" / "sync-trunk-to-gitlab.sh"
SYNC_GT = REPO / "tools" / "sync-trunk-to-gitea.sh"


# ── test_gitea_admin_provisioning ───────────────────────────────────────────
# 2026-05-18: the Gitea CLI refuses root; post.yml exec'd without `-u git` under
# `failed_when: false`, so the admin was never created and the role stayed green
# for two days. Pins `-u git` on every admin call and a loud diagnose step.

def test_gitea_admin_exec_uses_git_user():
    """Every `docker compose exec ... gitea admin user` invocation MUST
    pass `-u git`. The Gitea CLI checks effective UID and exits with
    a fatal log if root."""
    src = POST.read_text()
    # Find every occurrence of "exec ... gitea gitea admin user".
    pattern = re.compile(r"exec[^\n]*?gitea\s+gitea\s+admin\s+user", re.MULTILINE)
    matches = pattern.findall(src)
    assert matches, "no `gitea admin user` exec found — post.yml restructured?"
    for m in matches:
        assert "-u git" in m, (
            f"gitea exec missing `-u git` — CLI will fail as root: {m!r}"
        )


def test_gitea_post_surfaces_unexpected_admin_list_failure():
    """The admin-list task swallows failure via `failed_when: false` so later
    tasks can branch on rc. A diagnostic fail must catch *unexpected* return
    codes (anything other than 0 = found, 1 = grep miss)."""
    src = POST.read_text()
    assert "Diagnose admin-list call" in src
    # The condition must reject rc not in [0, 1].
    assert "rc | default(0) not in [0, 1]" in src


# ── test_gitea_sso_guard_knows_the_run_shape ────────────────────────────────
# Blank 2026-09-29: post.yml's lockout guard demanded the Authentik OAuth source
# before authentik_service_post.yml (later in the play) registered it, so every
# from-blank converge failed. The guard fires on a tag-restricted run only; the
# full run keeps its own loud verify. Evaluates the `when` list as Ansible does.

ASP = REPO / "tasks/stacks/authentik_service_post.yml"


def _guard() -> dict:
    tasks = yaml.safe_load(POST.read_text(encoding="utf-8"))
    return next(t for t in tasks if "refuse a hidden form" in t.get("name", ""))


def _fires(run_tags: list[str], auth_list: str) -> bool:
    env = jinja2.Environment()
    env.filters["bool"] = lambda v: str(v).lower() in ("1", "true", "yes")
    ctx = {
        "_gitea_container": {"stdout": "devops-gitea-1"},
        "install_authentik": True,
        "sso_autologin": True,
        "_gitea_idp_guard": {"stdout": auth_list},
        "ansible_run_tags": run_tags,
    }
    return all(env.from_string("{{ (" + w + ") | string }}").render(**ctx) == "True"
               for w in _guard()["when"])


def test_a_full_run_defers_to_the_service_side_verify() -> None:
    assert not _fires(["all"], "")


def test_a_tag_restricted_run_still_refuses_the_lockout() -> None:
    assert _fires(["gitea"], "")
    assert not _fires(["gitea"], "1  authentik  OAuth2")


def test_the_full_run_verify_is_loud() -> None:
    tasks = yaml.safe_load(ASP.read_text(encoding="utf-8"))
    verify = next(t for t in tasks if "Verify the Authentik OAuth2 source" in t.get("name", ""))
    assert "'authentik' not in" in verify["failed_when"]


# ── test_gitea_28_egress_names_auth ─────────────────────────────────────────
# Gitea 28 moved egress to one [security] ALLOWED_HOST_LIST (go-gitea#39426) for
# webhooks AND OAuth2; auth.<tld> is a private host-gateway address, so a 28
# render keeping only [webhook] is an SSO lockout. Below 28 the old key stays.
# Renders the real template.

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


# ── test_gitea_forge_sync_not_mirror ────────────────────────────────────────
# With gitea_agent_forge=true Gitea is a writable repo, so `mirror-sync` 400s;
# the real GitHub→Gitea sync is a fast-forward push (sync-trunk-to-gitea.sh).
# Pins nos-push's branch and the trunk-sync job on both forges, so the loop's
# base does not silently lag origin (the REM-250 stall).

def test_nos_push_runs_trunk_sync_in_agent_forge_mode():
    src = NOS_PUSH.read_text(encoding="utf-8")
    assert "gitea_agent_forge" in src, "nos-push must branch on agent-forge mode"
    assert "sync-trunk-to-gitea.sh" in src, "agent-forge push must run the trunk sync"
    # The mirror-sync API CALL (the curl, not a comment) must be GATED behind
    # the agent-forge check, in the else branch.
    call = re.search(r'-X POST -H "Authorization: token', src)
    assert call, "the mirror-sync POST is gone entirely — expected it in the else branch"
    assert src.index("gitea_agent_forge") < call.start(), \
        "the mirror-sync POST must sit after the agent-forge test, in the else branch"


def test_sync_trunk_is_a_clean_noop_off_agent_forge():
    src = SYNC_GT.read_text(encoding="utf-8")
    assert "install_gitea" in src and re.search(r"no-?op", src, re.I), \
        "sync-trunk must no-op when Gitea is not installed (GitLab-as-replacement)"
    assert "gitea_agent_forge" in src, \
        "sync-trunk must guard on agent-forge and no-op (not fail) in pull-mirror mode"


@pytest.mark.parametrize("forge", ["gitea", "gitlab"])
def test_trunk_sync_pulse_job_is_declared(forge):
    # SUBSTITUTABILITY (forge-topology doctrine): both forges carry the SAME
    # trunk-sync backbone, so present-or-absent either changes nothing.
    doc = yaml.safe_load((REPO / f"files/anatomy/plugins/{forge}-base/plugin.yml").read_text(encoding="utf-8"))
    jobs = (doc.get("pulse") or {}).get("jobs") or []
    match = [j for j in jobs
             if j.get("name") == "trunk-sync" and f"sync-trunk-to-{forge}.sh" in str(j.get("command", ""))]
    assert match, f"{forge}-base must schedule the trunk-sync backbone job"
    # forge-ahead (exit 10) is a promote signal, not a failure.
    assert 10 in (match[0].get("findings_exit_codes") or []), \
        f"exit 10 ({forge} trunk ahead) must be a finding, not a job failure"


def test_nos_push_syncs_gitlab_forge_symmetrically():
    src = NOS_PUSH.read_text(encoding="utf-8")
    assert "gitlab_agent_forge" in src and "sync-trunk-to-gitlab.sh" in src, \
        "nos-push must sync GitLab too when it is the agent forge (substitutability)"


def test_sync_trunk_gitlab_is_a_clean_noop_off_agent_forge():
    src = SYNC_GL.read_text(encoding="utf-8")
    assert "install_gitlab" in src and "gitlab_agent_forge" in src and re.search(r"no-?op", src, re.I), \
        "sync-trunk-to-gitlab must no-op unless GitLab is installed AND the agent forge"


# ── test_forge_gitlab_is_optional ───────────────────────────────────────────
# plat-forge-topology: Gitea + Woodpecker is primary, GitLab an optional drop-in
# (`install_gitlab`). T32.2 had inverted it after a playbook bug (2026-06-13
# phantom identity-providers POST). Red on a gitlab hard-fallback, a gitlab-only
# forge-sync excuse, or a trunk sync that ignores install_gitlab.

FORGE_SYNC = REPO / "tools" / "forge-sync.py"
LOOP_PR = REPO / "tools" / "loop-pr.py"
RECIPE_PR = REPO / "tools" / "recipe-pr.sh"
MIGRATION_PR = REPO / "tools" / "migration-pr.sh"


def test_stock_install_gitlab_is_off():
    cfg = ni.default_config_text()
    assert re.search(r"^install_gitlab:\s*false\b", cfg, re.M), (
        "install_gitlab must default false — GitLab is optional RAM, not the forge"
    )
    assert re.search(r"^install_gitea:\s*true\b", cfg, re.M), (
        "install_gitea must default true — Gitea + Woodpecker is primary"
    )
    assert re.search(r'^nos_agent_forge:\s*"gitea"', cfg, re.M), (
        "nos_agent_forge must default gitea; gitlab-as-default is the inversion"
    )


def test_recipe_and_migration_pr_do_not_hard_fallback_to_gitlab():
    for path in (RECIPE_PR, MIGRATION_PR):
        src = path.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in src.splitlines()
            if not line.lstrip().startswith("#")
        )
        assert 'FORGE="gitlab"' not in code, (
            f"{path.name} still hard-fallbacks to gitlab — GitLab is optional; "
            "the fallback is gitea, and install_gitlab=false must pin it"
        )
        assert 'FORGE="gitea"' in code
        assert "install_gitlab" in src


def test_forge_sync_excuses_any_declared_off_holder():
    """Not a GitLab special case. install_<forge> false excuses that seat."""
    src = FORGE_SYNC.read_text(encoding="utf-8")
    # The lookup must be the per-holder flag, not a gitlab-only `if name ==`.
    assert 'f"install_{name}"' in src or "f'install_{name}'" in src, (
        "forge-sync must key declared_off off install_<holder>, not a "
        "gitlab-only branch — otherwise a Gitea-off GitLab-replacement "
        "estate still elects a missing Gitea tip"
    )
    body = src.split('if name == "gitlab"', 1)
    # A gitlab-only declared_off branch is the old shape.
    if len(body) > 1:
        raise AssertionError(
            "forge-sync still special-cases gitlab for declared_off — "
            "use install_{name} for every forge holder"
        )


def test_loop_pr_does_not_hardcode_gitlab_in_the_push_set():
    src = LOOP_PR.read_text(encoding="utf-8")
    land = src.split("def land", 1)[1]
    assert "_gitlab_declared_on" in land or "_forge_installed" in land
    assert "_open_gitea_pr" in src


def test_trunk_sync_scripts_consult_the_install_flag():
    gl = SYNC_GL.read_text(encoding="utf-8")
    gt = SYNC_GT.read_text(encoding="utf-8")
    assert "install_gitlab" in gl, (
        "sync-trunk-to-gitlab.sh must no-op when GitLab is not installed"
    )
    assert "install_gitea" in gt, (
        "sync-trunk-to-gitea.sh must no-op when Gitea is not installed"
    )
