"""Anatomy CI gate — GitLab agent-forge wiring (T32.2, 2026-06-10).

The operator review surface moved Gitea → GitLab (the Gitea oauth2 source row
kept vanishing → /user/oauth2/authentik 500 → UI lockout; GitLab's omniauth
OIDC works). This pins the forge contract so its pieces can't drift apart:

  * pazny.gitlab defaults declare the forge vars (off by default)
  * post.yml includes post-forge.yml gated on gitlab_agent_forge
  * the PAT persists via secrets.yml.j2 (gitlab_api_token)
  * recipe-pr.sh targets GitLab MRs by default (nos_agent_forge=gitlab) and
    keeps the Gitea leg as an explicit fallback
  * the trunk-sync twin exists and is FF-only
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
GL_DEFAULTS = REPO / "roles" / "pazny.gitlab" / "defaults" / "main.yml"
GL_POST = REPO / "roles" / "pazny.gitlab" / "tasks" / "post.yml"
GL_FORGE = REPO / "roles" / "pazny.gitlab" / "tasks" / "post-forge.yml"
SECRETS_TPL = REPO / "templates" / "secrets.yml.j2"
RECIPE_PR = REPO / "tools" / "recipe-pr.sh"
SYNC_GL = REPO / "tools" / "sync-trunk-to-gitlab.sh"
DEFAULT_CONFIG = REPO / "default.config.yml"


def test_gitlab_forge_defaults_declared():
    text = GL_DEFAULTS.read_text()
    for var in ("gitlab_agent_forge", "gitlab_nos_repo_owner", "gitlab_nos_repo_name",
                "gitlab_forge_token_name", "gitlab_forge_token_scopes"):
        assert re.search(rf"^{var}:", text, re.M), f"{var} missing from pazny.gitlab defaults"
    assert re.search(r"^gitlab_agent_forge:\s*false", text, re.M), (
        "gitlab_agent_forge must default OFF (operator opts in via config.yml)"
    )


def test_post_includes_forge_gated():
    text = GL_POST.read_text()
    assert "post-forge.yml" in text, "post.yml must include post-forge.yml"
    block = text[text.index("post-forge.yml"):]
    assert "gitlab_agent_forge" in block, "post-forge include must be gated on gitlab_agent_forge"


def test_forge_pat_is_persisted_and_validated():
    assert GL_FORGE.exists(), "post-forge.yml missing"
    forge = GL_FORGE.read_text()
    # The mint Ruby lives in a STANDALONE script (Jinja-in-heredoc gate) fed via
    # stdin with env pass-through; the yml validates the persisted PAT + no_logs.
    rb = (REPO / "files" / "anatomy" / "scripts" / "gitlab-forge-pat.rb").read_text()
    assert "set_token" in rb, "PAT must be minted via rails set_token (known value)"
    assert "revoke!" in rb, "stale same-name tokens must be revoked before the mint"
    assert "ENV.fetch" in rb, "script takes values from env (pass-through), not argv/Jinja"
    assert "gitlab-forge-pat.rb" in forge, "post-forge.yml must invoke the standalone mint script"
    assert "/api/v4/user" in forge, "persisted PAT must be validated against /api/v4/user"
    assert "401" in forge, "validate probe must tolerate 401 (regenerate path)"
    assert "no_log: true" in forge, "token-bearing tasks must be no_log"
    # Jinja comment-open trap (the backup.sh lesson): no brace-hash anywhere.
    assert "{" + "#" not in forge, "Jinja comment-open sequence found in post-forge.yml"
    # Ruby-interpolation SyntaxError trap (killed the root-pw reconverge for
    # weeks): error lines must use concat, never an interpolated escaped quote.
    for script in ("gitlab-forge-pat.rb", "gitlab-root-password.rb"):
        body = (REPO / "files" / "anatomy" / "scripts" / script).read_text()
        assert '#{' not in body, f"{script}: no Ruby string interpolation (concat only)"
    # Persistence template carries the var (for the LOAD side — include_vars).
    assert re.search(r"^gitlab_api_token:", SECRETS_TPL.read_text(), re.M), (
        "secrets.yml.j2 must persist gitlab_api_token"
    )


def test_forge_pat_persisted_in_role_after_mint():
    """The central secrets.yml.j2 render runs BEFORE stack-up reaches post-forge,
    so a set_fact alone dies with the play (live-confirmed CRIT, 2026-06-10).
    post-forge.yml must write the token itself via lineinfile, AFTER the mint.
    Same contract for the gitea twin."""
    for path, var, mint_marker in (
            (GL_FORGE, "gitlab_api_token", "gitlab-forge-pat.rb"),
            (REPO / "roles" / "pazny.gitea" / "tasks" / "post-forge.yml", "gitea_api_token", "tokens")):
        text = path.read_text()
        assert "ansible.builtin.lineinfile" in text, f"{path.name} must persist {var} in-role via lineinfile"
        m = re.search(rf"regexp:\s*'\^{var}:'", text)
        assert m, f"{path.name} lineinfile must target ^{var}:"
        # Match the MODULE invocation (a header comment may mention lineinfile
        # before the mint — that tripped the first version of this assertion).
        assert text.index("ansible.builtin.lineinfile") > text.index(mint_marker), (
            f"{path.name}: the lineinfile persistence must come AFTER the mint"
        )


def test_recipe_pr_defaults_to_gitlab_mrs():
    text = RECIPE_PR.read_text()
    assert "nos_agent_forge" in text, "recipe-pr.sh must read the nos_agent_forge config var"
    assert 'FORGE="gitlab"' in text, "recipe-pr.sh hard fallback must be gitlab"
    assert "PRIVATE-TOKEN" in text and "merge_requests" in text, "GitLab MR leg missing"
    assert "api/v1/repos" in text and "pulls" in text, "Gitea PR fallback leg removed"
    cfg = DEFAULT_CONFIG.read_text()
    assert re.search(r'^nos_agent_forge:\s*"gitlab"', cfg, re.M), (
        "default.config.yml must declare nos_agent_forge: gitlab"
    )


def test_sync_twin_exists_and_is_ff_only():
    text = SYNC_GL.read_text()
    assert "refs/remotes/origin/" in text, "sync must push the fetched GitHub ref"
    # FF-only: no force flag NOR a +refspec on any actual push COMMAND (prose
    # like "No --force" in comments is fine — match the git invocation).
    assert not re.search(r"git push[^\n]*(--force|-f\b)", text), "trunk sync must NEVER force-push"
    assert not re.search(r'git push[^\n]*"\+', text), "trunk sync must not use +refspec (force) either"
    assert "gitlab_api_token" in text, "sync must discover the forge PAT"
