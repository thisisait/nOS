"""Anatomy CI gate — WordPress RBAC mirror + site-polish contract.

Pins (devlog follow-up, 2026-06-13):
  - rbac-role-sync.php mu-plugin exists, is staged (install_authentik-gated)
    and ro-mounted; it hooks BOTH openid-connect-generic actions (create +
    update-using-current-claim) so demotion happens on re-login, not only on
    first login;
  - the group->role map is a JSON STRING literal var (to_json is an ansible
    filter — the vars-files stock-Jinja trap forbids it in default.config.yml)
    that parses and maps all four nOS tiers; the wordpress-base compose
    extension renders it into WP_OIDC_GROUP_ROLE_MAP;
  - theme + extra-plugin install tasks exist in post.yml behind is-active
    checks (steady-state changed=0) and the defaults name generatepress +
    secure-custom-fields;
  - the onlyoffice image is a var (euro-office pilot flip) with the stock
    default and a pinned version.
"""
from __future__ import annotations

import json
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles/pazny.wordpress"
MU = ROLE / "files/rbac-role-sync.php"
COMPOSE_EXT = REPO / "files/anatomy/plugins/wordpress-base/templates/wordpress-base.compose.yml.j2"
CONFIG = REPO / "default.config.yml"


def _config() -> dict:
    return yaml.safe_load(
        CONFIG.read_text(encoding="utf-8").replace("{{", "RAW_").replace("}}", "_RAW")
    )


def test_mu_plugin_hooks_both_actions():
    src = MU.read_text(encoding="utf-8")
    assert "openid-connect-generic-user-create" in src
    assert "openid-connect-generic-update-user-using-current-claim" in src
    assert "set_role" in src


def test_mu_plugin_staged_and_mounted():
    main_tasks = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
    assert "rbac-role-sync.php" in main_tasks
    # mu-plugins ship as ONE directory mount (single-file mounts break on a
    # fresh blank with external/virtiofs storage — "outside of rootfs").
    compose = (ROLE / "templates/compose.yml.j2").read_text(encoding="utf-8")
    assert "/wp-content/mu-plugins:ro" in compose, "mu-plugins must be a directory mount"
    assert "mu-plugins/rbac-role-sync.php:" not in compose, "no per-file mounts"


def test_role_map_is_json_literal_covering_all_tiers():
    raw = CONFIG.read_text(encoding="utf-8")
    line = next(l for l in raw.splitlines() if l.startswith("wordpress_rbac_role_map_json:"))
    payload = line.split(":", 1)[1].strip().strip("'\"")
    role_map = json.loads(payload)  # must be literal JSON, no Jinja
    assert "{{" not in payload, "role map must be a literal (stock-Jinja trap)"
    for group in ("nos-providers", "nos-admins", "nos-managers", "nos-users", "nos-guests"):
        assert group in role_map, f"role map missing tier group {group}"
    assert set(role_map.values()) <= {"administrator", "editor", "author", "contributor", "subscriber"}
    ext = COMPOSE_EXT.read_text(encoding="utf-8")
    assert "WP_OIDC_GROUP_ROLE_MAP" in ext and "wordpress_rbac_role_map_json" in ext


def test_site_polish_tasks_and_defaults():
    post = (ROLE / "tasks/post.yml").read_text(encoding="utf-8")
    assert "wp theme install {{ wordpress_theme }}" in post
    assert "wp theme is-active" in post and "wp plugin is-active" in post
    cfg = _config()
    assert cfg["wordpress_theme"] == "generatepress"
    assert "secure-custom-fields" in cfg["wordpress_extra_plugins"]


def test_onlyoffice_image_is_flippable_var():
    tmpl = (REPO / "roles/pazny.onlyoffice/templates/compose.yml.j2").read_text(encoding="utf-8")
    assert "{{ onlyoffice_image | default('onlyoffice/documentserver') }}" in tmpl
    defaults = (REPO / "roles/pazny.onlyoffice/defaults/main.yml").read_text(encoding="utf-8")
    assert "euro-office" in defaults, "pilot flip instructions must live in the role defaults"
