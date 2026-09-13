"""Anatomy CI gate — GitLab is never assumed always-on.

plat-forge-topology: Gitea + Woodpecker is PRIMARY; GitLab is an optional
drop-in replacement (`install_gitlab`), never a second forge the loop, the
trunk sync, or recipe-pr reach for by default.

The inversion this pins closed: T32.2 made GitLab the agent forge because
the Gitea oauth2 source row vanished. That vanish was a playbook bug
(phantom `POST /api/v1/admin/identity-providers`, 2026-06-13 SSO audit) —
not a reason to keep GitLab as the stock review surface.

A check that cannot fail on the inverted tree does not pin anything: this
gate fails if recipe-pr/migration-pr hard-fallback to gitlab, if forge-sync
only excuses GitLab by name, or if trunk-sync-to-gitlab runs without
consulting `install_gitlab`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO / "default.config.yml"
FORGE_SYNC = REPO / "tools" / "forge-sync.py"
LOOP_PR = REPO / "tools" / "loop-pr.py"
RECIPE_PR = REPO / "tools" / "recipe-pr.sh"
MIGRATION_PR = REPO / "tools" / "migration-pr.sh"
SYNC_GL = REPO / "tools" / "sync-trunk-to-gitlab.sh"
SYNC_GT = REPO / "tools" / "sync-trunk-to-gitea.sh"


def test_stock_install_gitlab_is_off():
    cfg = DEFAULT_CONFIG.read_text(encoding="utf-8")
    assert re.search(r"^install_gitlab:\s*false\b", cfg, re.M), (
        "install_gitlab must default false — GitLab is optional RAM, not the forge"
    )
    assert re.search(r"^install_gitea:\s*true\b", cfg, re.M), (
        "install_gitea must default true — Gitea + Woodpecker is primary"
    )
    # Behaviour pin is install_gitlab + tool override, not the nos_agent_forge
    # string (that default may still read gitlab in a mixed working tree).
    recipe = RECIPE_PR.read_text(encoding="utf-8")
    assert "install_gitlab" in recipe and 'FORGE="gitea"' in recipe


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
