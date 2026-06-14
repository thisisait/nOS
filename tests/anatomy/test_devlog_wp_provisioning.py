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

Blank-safety of the secret-persistence strategy (the lineinfile choice is what
makes the app password survive — and regenerate across — a blank reset). The
full cycle is gated end-to-end so an accidental flip to a template re-render
(which would NOT regenerate the password on a blank → devlog REST writes 401)
cannot land silently:
  - blank-reset.yml removes ~/.nos/secrets.yml so the password is force-
    regenerated on the next run;
  - the mint decision (`_wp_devlog_pw_stale`) re-mints when the persisted var
    is empty (length == 0) — exactly the post-blank state;
  - the persist task is a lineinfile with create:true (handles the missing
    file the blank just produced) — never a template re-render;
  - the secrets template carries the default('') gate so the missing var
    renders without error.
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
BLANK_RESET = REPO / "tasks/blank-reset.yml"


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


# ── Blank-safety of the secret-persistence cycle ────────────────────────────

def test_blank_reset_removes_persisted_secrets():
    """Leg 1: blank=true wipes ~/.nos/secrets.yml so the devlog app password
    is force-regenerated on the next run (no stale credential survives)."""
    tasks = yaml.safe_load(BLANK_RESET.read_text(encoding="utf-8"))
    removers = [
        t for t in tasks
        if str(t.get("ansible.builtin.file", {}).get("path", "")).endswith(
            "/.nos/secrets.yml")
        and t.get("ansible.builtin.file", {}).get("state") == "absent"
    ]
    assert removers, (
        "blank-reset.yml must remove ~/.nos/secrets.yml (state: absent) so the "
        "devlog app password regenerates on the post-blank run"
    )


def test_mint_decision_remints_when_persisted_secret_empty():
    """Leg 2: the stale-decision re-mints when the persisted var is empty
    (length == 0) — the exact state a blank leaves (file removed → default(''))."""
    tasks = yaml.safe_load(DEVLOG_TASKS.read_text(encoding="utf-8"))
    decide = next(
        (t for t in tasks
         if "_wp_devlog_pw_stale" in str(t.get("ansible.builtin.set_fact", ""))),
        None,
    )
    assert decide is not None, "expected the _wp_devlog_pw_stale decision task"
    expr = str(decide["ansible.builtin.set_fact"]["_wp_devlog_pw_stale"])
    assert "wordpress_devlog_app_password | default('')" in expr
    assert "| length == 0" in expr, (
        "stale-decision must treat an empty persisted secret (post-blank) as "
        "a re-mint trigger"
    )


def test_persist_is_lineinfile_create_true_not_template():
    """Leg 3: the persist task is a lineinfile that CREATES the file if missing
    (the blank just removed it) — never a template re-render (which runs before
    stack-up and would clobber the append / not regenerate on a blank)."""
    tasks = yaml.safe_load(DEVLOG_TASKS.read_text(encoding="utf-8"))
    persist = next(
        (t for t in tasks
         if "lineinfile" in t
         and "wordpress_devlog_app_password" in str(t["lineinfile"])
         or "ansible.builtin.lineinfile" in t
         and "wordpress_devlog_app_password" in str(t["ansible.builtin.lineinfile"])),
        None,
    )
    assert persist is not None, "expected the lineinfile persist task in devlog.yml"
    li = persist.get("ansible.builtin.lineinfile") or persist.get("lineinfile")
    assert str(li["path"]).endswith("/.nos/secrets.yml")
    assert li.get("create") is True, (
        "create: true is the blank-safety pin — lineinfile must (re)create the "
        "file the blank removed; a missing create: would fail on the post-blank run"
    )
    # And the secrets template must NOT be the persistence path for this var
    # (a template re-render runs before stack-up → would never carry the
    # minted value forward).
    tmpl = SECRETS_TMPL.read_text(encoding="utf-8")
    assert "wordpress_devlog_app_password: \"{{ wordpress_devlog_app_password | default('') }}\"" in tmpl, (
        "secrets template must read the var with a default('') gate, not mint it"
    )


def test_secrets_template_renders_with_var_absent():
    """Leg 4: the secrets template's default('') gate renders cleanly when the
    var is undefined (the post-blank state, before devlog.yml re-mints)."""
    from jinja2 import Environment

    line = "wordpress_devlog_app_password: \"{{ wordpress_devlog_app_password | default('') }}\""
    env = Environment()
    # var absent → renders to empty string, no UndefinedError
    rendered = env.from_string(line).render({})
    assert rendered == 'wordpress_devlog_app_password: ""'
    # var present → carries the value through
    rendered2 = env.from_string(line).render(
        {"wordpress_devlog_app_password": "abcd EFGH ijkl"})
    assert rendered2 == 'wordpress_devlog_app_password: "abcd EFGH ijkl"'
