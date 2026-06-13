"""Anatomy CI gate — devlog WordPress provisioning contract.

Pins (roles/pazny.wordpress + wordpress-base plugin):
  - tasks/devlog.yml exists and is included from post.yml behind
    wordpress_devlog_enabled;
  - the app-password mint + persist tasks carry no_log (the password is a
    write credential for the public-facing CMS);
  - the persistence is lineinfile into ~/.nos/secrets.yml (NOT a template
    re-render — the central secrets render runs before stack-up, gitea forge
    precedent) and templates/secrets.yml.j2 carries the default('') line;
  - the app-passwords mu-plugin is staged + ro-mounted (core disables
    Application Passwords on non-SSL requests; TLS terminates at Traefik);
  - the post_compose hook documents the deliberate non-mirror of devlog.yml;
  - the new config vars exist with real defaults (stock-Jinja trap is covered
    separately by test_config_stock_jinja_only.py).
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles/pazny.wordpress"
DEVLOG_TASKS = ROLE / "tasks/devlog.yml"
POST_TASKS = ROLE / "tasks/post.yml"
MU_PLUGIN = ROLE / "files/devlog-app-passwords.php"
COMPOSE = ROLE / "templates/compose.yml.j2"
HOOK = REPO / "files/anatomy/plugins/wordpress-base/hooks/post_compose.yml"
SECRETS_TMPL = REPO / "templates/secrets.yml.j2"
CONFIG = REPO / "default.config.yml"


def test_devlog_tasks_exist_and_included():
    assert DEVLOG_TASKS.is_file()
    post = POST_TASKS.read_text(encoding="utf-8")
    assert "devlog.yml" in post
    assert "wordpress_devlog_enabled" in post


def test_secret_tasks_carry_no_log():
    tasks = yaml.safe_load(DEVLOG_TASKS.read_text(encoding="utf-8"))
    sensitive = [
        t for t in tasks
        if "application-password create" in str(t.get("ansible.builtin.shell", ""))
        or "set_fact" in t and "wordpress_devlog_app_password" in str(t)
        or "lineinfile" in str(t.keys())
    ]
    for task in tasks:
        text = str(task)
        if "wordpress_devlog_app_password" in text or "application-password create" in text:
            assert task.get("no_log") is True, f"missing no_log: {task.get('name')}"
    assert sensitive, "expected the mint/persist tasks in devlog.yml"


def test_persistence_is_lineinfile_with_template_default():
    src = DEVLOG_TASKS.read_text(encoding="utf-8")
    assert "lineinfile" in src and "secrets.yml" in src
    tmpl = SECRETS_TMPL.read_text(encoding="utf-8")
    assert "wordpress_devlog_app_password: \"{{ wordpress_devlog_app_password | default('') }}\"" in tmpl


def test_mu_plugin_staged_and_mounted():
    assert MU_PLUGIN.is_file()
    assert "wp_is_application_passwords_available" in MU_PLUGIN.read_text(encoding="utf-8")
    main_tasks = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
    # Staged into the mu-plugins dir behind the devlog flag; the whole dir is
    # mounted (single directory mount — file mounts break on a fresh blank with
    # external/virtiofs storage), so WP loads it.
    assert "devlog-app-passwords.php" in main_tasks
    assert "wordpress_devlog_enabled" in main_tasks
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "/wp-content/mu-plugins:ro" in compose, "mu-plugins must be a directory mount"


def test_hook_documents_the_non_mirror():
    hook = HOOK.read_text(encoding="utf-8")
    assert "devlog" in hook.lower(), (
        "post_compose hook header must document why devlog.yml is role-only"
    )
    assert "byte-for-byte" not in hook, "stale byte-for-byte mirror claim"


def test_config_vars_have_real_defaults():
    cfg = CONFIG.read_text(encoding="utf-8")
    for var in ("wordpress_devlog_enabled", "wordpress_devlog_bot_user",
                "wordpress_devlog_app_name"):
        assert f"\n{var}:" in cfg, f"{var} missing from default.config.yml"
