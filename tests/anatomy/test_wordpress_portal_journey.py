"""One journey through the pazny.wordpress role: the OIDC plugin it installs and
verifies, the claims and roles that login maps, the mu-plugins it stages and
removes, the portal pages it creates, and the ceiling that keeps it out of the books.

Absorbed (2026-11-08, roadmap gate-diet-role-journeys), one section each:
  test_wordpress_oidc_install_verified, test_wordpress_oidc_formats_use_sent_claims,
  test_wordpress_rbac_mirror, test_wordpress_mu_plugins_blank_safety,
  test_a_flag_removes_what_it_staged, test_wordpress_portal_pages_task_runs,
  test_wordpress_client_portal_ceiling.
Every assert of those files survives here with the same inputs and expectations.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

ROLE = REPO / "roles/pazny.wordpress"
MAIN = ROLE / "tasks/main.yml"
POST = ROLE / "tasks/post.yml"
DEFAULTS = ROLE / "defaults/main.yml"
COMPOSE = ROLE / "templates/compose.yml.j2"
PLUGIN_DIR = REPO / "files" / "anatomy" / "plugins" / "wordpress-base"
HOOK = PLUGIN_DIR / "hooks" / "post_compose.yml"


# ── test_wordpress_oidc_install_verified ────────────────────────────────────
# SSO audit (sso-wordpress-oidc-plugin-install-silent): the install task's
# failed_when:false masked a wp.org timeout, so the mu-plugin configured a
# missing plugin and the Authentik redirect 404'd. A separate LOUD verify runs
# `wp plugin is-active`, and the wordpress-base hook mirrors it.

PLUGIN_SLUG = "daggerhart-openid-connect-generic"


def _post_tasks() -> list[dict]:
    return yaml.safe_load(POST.read_text(encoding="utf-8"))


def _shell(task: dict) -> str:
    return str(task.get("ansible.builtin.shell", ""))


def test_role_has_loud_oidc_verify_task():
    tasks = _post_tasks()
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
    tasks = _post_tasks()
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
    that silently dropped to inactive between runs would skip the verify exactly
    when it's needed."""
    tasks = _post_tasks()
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
    tasks = _post_tasks()
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


# ── test_wordpress_oidc_formats_use_sent_claims ─────────────────────────────
# 2026-10-01: displayname_format '{given_name} {family_name}' — Authentik's
# profile scope sends no family_name, so every SSO login failed with
# incomplete-user-claim. The formats name only claims Authentik sends.

OIDC_MU = ROLE / "files/oidc-mu-plugin.php"
# Authentik's default openid/email/profile scope mappings
SENT = {"sub", "email", "email_verified", "name", "given_name", "preferred_username", "nickname", "groups"}


def test_every_format_claim_is_sent():
    formats = re.findall(r"'\w+_format'\s*=>\s*'([^']*)'", OIDC_MU.read_text())
    assert formats
    used = {c for f in formats for c in re.findall(r"\{(\w+)\}", f)}
    assert used <= SENT, used - SENT


# ── test_wordpress_rbac_mirror ──────────────────────────────────────────────
# 2026-06-13: rbac-role-sync.php hooks both openid-connect actions so demotion
# happens on re-login; the group->role map is a literal JSON string (stock-Jinja
# trap) covering every tier; theme/plugin installs sit behind is-active checks;
# the onlyoffice image stays a flippable var (euro-office pilot).

RBAC_MU = ROLE / "files/rbac-role-sync.php"
COMPOSE_EXT = PLUGIN_DIR / "templates" / "wordpress-base.compose.yml.j2"


def _config() -> dict:
    return yaml.safe_load(
        ni.default_config_text().replace("{{", "RAW_").replace("}}", "_RAW")
    )


def test_mu_plugin_hooks_both_actions():
    src = RBAC_MU.read_text(encoding="utf-8")
    assert "openid-connect-generic-user-create" in src
    assert "openid-connect-generic-update-user-using-current-claim" in src
    assert "set_role" in src


def test_mu_plugin_staged_and_mounted():
    main_tasks = MAIN.read_text(encoding="utf-8")
    assert "rbac-role-sync.php" in main_tasks
    # mu-plugins ship as ONE directory mount (single-file mounts break on a
    # fresh blank with external/virtiofs storage — "outside of rootfs").
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "/wp-content/mu-plugins:ro" in compose, "mu-plugins must be a directory mount"
    assert "mu-plugins/rbac-role-sync.php:" not in compose, "no per-file mounts"


def test_role_map_is_json_literal_covering_all_tiers():
    raw = ni.default_config_text()
    line = next(l for l in raw.splitlines() if l.startswith("wordpress_rbac_role_map_json:"))  # noqa: E741
    payload = line.split(":", 1)[1].strip().strip("'\"")
    role_map = json.loads(payload)  # must be literal JSON, no Jinja
    assert "{{" not in payload, "role map must be a literal (stock-Jinja trap)"
    for group in ("nos-providers", "nos-admins", "nos-managers", "nos-users", "nos-guests"):
        assert group in role_map, f"role map missing tier group {group}"
    assert set(role_map.values()) <= {"administrator", "editor", "author", "contributor", "subscriber"}
    ext = COMPOSE_EXT.read_text(encoding="utf-8")
    assert "WP_OIDC_GROUP_ROLE_MAP" in ext and "wordpress_rbac_role_map_json" in ext


def test_site_polish_tasks_and_defaults():
    post = POST.read_text(encoding="utf-8")
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


# ── test_wordpress_mu_plugins_blank_safety ──────────────────────────────────
# 7f8541be (2026-06-13): per-file mu-plugin bind mounts died "outside of rootfs"
# on a fresh blank with wordpress_dir on virtiofs, so the iiab stack-up failed.
# One directory mount; every *.php staged into it, the dir created first, every
# copy before the compose render, never a per-file mount.

FILES = ROLE / "files"
STAGING_DIR = "{{ stacks_dir }}/iiab/wordpress/mu-plugins"


def _main_tasks() -> list[dict]:
    return yaml.safe_load(MAIN.read_text(encoding="utf-8"))


def _php_sources() -> list[str]:
    return sorted(p.name for p in FILES.glob("*.php"))


def test_there_are_mu_plugin_sources():
    # Guard against the role's files/ dir being emptied/renamed out from under
    # the enumeration (which would make the per-file gate vacuously pass).
    srcs = _php_sources()
    assert srcs, "expected at least one *.php mu-plugin in roles/pazny.wordpress/files/"


def test_every_php_source_is_staged():
    tasks = _main_tasks()
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
    tasks = _main_tasks()
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
    tasks = _main_tasks()
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
    # No per-file mountpoint may sneak back in — that is the regression 7f8541be fixed.
    per_file = re.search(r"mu-plugins/[\w.-]+\.php:", compose)
    assert per_file is None, f"per-file mu-plugin mount forbidden: {per_file.group(0) if per_file else ''}"


# ── test_a_flag_removes_what_it_staged ──────────────────────────────────────
# 2026-08-06: three mu-plugins were staged behind flags and none removed, and
# WordPress auto-loads mu-plugins/ — flipping wordpress_cve_63030_mitigate off
# would have left /wp-json/batch/v1/ dead forever. Every conditional copy into
# the auto-load dir has a remover on the negated condition.

#: The auto-load surface. A file landing here runs on the next request with no
#: further step, which is what makes an un-removed copy invisible.
AUTOLOAD_DIR = "mu-plugins/"


def _dict_tasks(path: Path) -> list[dict]:
    docs = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [t for t in docs if isinstance(t, dict)]


def _staged_conditionally(tasks: list[dict]) -> dict[str, str]:
    """{filename: the `when` that gates it} for conditional copies into the
    auto-load directory."""
    out: dict[str, str] = {}
    for task in tasks:
        copy = task.get("ansible.builtin.copy") or task.get("copy")
        if not isinstance(copy, dict):
            continue
        dest = str(copy.get("dest", ""))
        if AUTOLOAD_DIR not in dest:
            continue
        when = task.get("when")
        if when is None:
            continue  # unconditional: always present, nothing to undo
        out[dest.rsplit("/", 1)[-1]] = str(when)
    return out


def _removed(tasks: list[dict]) -> set[str]:
    """Filenames some task can delete from the auto-load directory."""
    removed: set[str] = set()
    for task in tasks:
        file_mod = task.get("ansible.builtin.file") or task.get("file")
        if not isinstance(file_mod, dict) or file_mod.get("state") != "absent":
            continue
        path = str(file_mod.get("path", ""))
        if AUTOLOAD_DIR not in path:
            continue
        # Either a literal filename, or a loop whose items name them.
        literal = path.rsplit("/", 1)[-1]
        if "{{" not in literal:
            removed.add(literal)
            continue
        for item in task.get("loop") or []:
            if isinstance(item, dict):
                for value in item.values():
                    if isinstance(value, str) and value.endswith(".php"):
                        removed.add(value)
            elif isinstance(item, str) and item.endswith(".php"):
                removed.add(item)
    return removed


def test_every_conditionally_staged_mu_plugin_can_be_removed():
    tasks = _dict_tasks(MAIN)
    staged = _staged_conditionally(tasks)
    assert staged, (
        "no conditionally staged mu-plugin found — either the role changed "
        "shape or this gate has gone blind and is passing on an empty set"
    )

    removed = _removed(tasks)
    orphans = sorted(set(staged) - removed)
    assert not orphans, (
        "these mu-plugins are staged behind a flag and nothing removes them "
        "when it goes false. WordPress auto-loads mu-plugins/, so the last "
        "copy keeps running with no activation step and no UI to notice it "
        "in:\n  " + "\n  ".join(f"{f}  (staged when: {staged[f]})" for f in orphans)
    )


def test_the_removal_fires_on_the_negation_of_the_staging_condition():
    """Removal gated by the SAME condition as staging would delete the file it
    just wrote. The negation is the whole point, so it is asserted rather than
    assumed from the task's name."""
    tasks = _dict_tasks(MAIN)
    removers = [
        t for t in tasks
        if isinstance(t.get("ansible.builtin.file"), dict)
        and t["ansible.builtin.file"].get("state") == "absent"
        and AUTOLOAD_DIR in str(t["ansible.builtin.file"].get("path", ""))
    ]
    assert removers, "no removal task for the auto-load directory"
    for task in removers:
        when = str(task.get("when", ""))
        assert re.search(r"\bnot\b", when), (
            f"the mu-plugin removal task's condition is {when!r} — without a "
            f"negation it deletes what the staging task just wrote"
        )


def test_the_mitigation_file_survives_its_own_flag():
    """Keeping the CVE mu-plugin is deliberate: a rollback to the vulnerable core
    is exactly when the mitigation is wanted again, and `when: true` against a
    missing `src:` fails the play rather than protecting anything."""
    php = ROLE / "files/cve-2026-63030-batch-block.php"
    assert php.is_file(), (
        "cve-2026-63030-batch-block.php was deleted. wordpress_cve_63030_"
        "mitigate can still be set to true, and the copy task would then fail "
        "on a missing source — a flag that cannot be turned back on."
    )


# ── test_wordpress_portal_pages_task_runs ───────────────────────────────────
# Blank 2026-09-29: the portal-pages task used a folded scalar (`>`); YAML keeps
# the newlines of more-indented lines, so the `if` body became four commands and
# failed "wp: command not found" on every first install. Rendered as Ansible
# does and run under a stub docker; the create call must arrive whole.

def _portal_task() -> dict:
    tasks = yaml.safe_load(POST.read_text(encoding="utf-8"))
    return next(t for t in tasks if t.get("name", "").endswith("Ensure client portal pages"))


def test_the_create_call_arrives_as_one_command(tmp_path: Path) -> None:
    stub = tmp_path / "docker"
    log = tmp_path / "calls.log"
    stub.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nexit 0\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    env = jinja2.Environment()
    env.filters["quote"] = lambda v: "'" + str(v).replace("'", "'\\''") + "'"
    page = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))["wordpress_portal_pages"][0]
    script = env.from_string(_portal_task()["ansible.builtin.shell"]).render(docker_bin=str(stub), item=page)

    run = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True,
                         env={**os.environ, "PATH": str(tmp_path)})
    assert run.returncode == 0 and run.stderr == "", run.stderr
    calls = log.read_text().splitlines()
    assert len(calls) == 2, calls
    assert "wp post create" in calls[1] and page["content"] in calls[1], calls[1]


# ── test_wordpress_client_portal_ceiling ────────────────────────────────────
# Week-1 commons pin: WordPress (native_oidc) is the gated client portal —
# statements, shareable PDFs, contact form — and never writes the books
# (pending-invoice-verify, journals, postings stay in KEAP). Retro-red on the
# pre-pin GDPR subjects and the "Public website / blog" hub card.

PLUGIN = PLUGIN_DIR / "plugin.yml"

# Exact table/queue names the books write. Substring match so a compose
# write target or a pulse writes: block cannot sneak in unnamed.
BOOK_WRITE_TOKENS = (
    "pending-invoice-verify",
    "journal-entry",
    "posting",
)


def _manifest() -> dict:
    return yaml.safe_load(PLUGIN.read_text(encoding="utf-8"))


def test_gdpr_names_clients_and_the_portal_ceiling():
    gdpr = _manifest()["gdpr"]
    subjects = gdpr["data_subjects"]
    assert "clients" in subjects, (
        "wordpress-base GDPR subjects omit clients — the gated portal "
        "processes client PII (statements, PDFs, contact form)"
    )
    purpose = gdpr["purpose"]
    assert "portal" in purpose.lower()
    assert "not the books" in purpose.lower()
    blob = purpose.lower()
    assert "statement" in blob or "pdf" in blob
    assert "contact" in blob


def test_hub_card_names_the_portal_not_a_public_blog():
    card = _manifest()["ui-extension"]["hub_card"]
    desc = card["description"]
    assert "Public website / blog" not in desc
    lower = desc.lower()
    assert "portal" in lower
    assert "not the books" in lower


def test_sso_stays_native_oidc_at_declared_tier():
    auth = _manifest()["authentik"]
    assert auth["mode"] == "native_oidc"
    assert auth["tier"] == 4


def test_wordpress_base_does_not_write_the_books():
    hits: list[str] = []
    for path in PLUGIN_DIR.rglob("*"):
        if not path.is_file() or path.suffix in {".png", ".jpg", ".woff", ".woff2"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in BOOK_WRITE_TOKENS:
            if token in text:
                hits.append(f"{path.relative_to(REPO)}:{token}")
    assert not hits, (
        "wordpress-base names a books write surface "
        f"{hits} — WP is the portal, not pending-invoice-verify / journals / posting"
    )


def test_post_hooks_create_portal_pages_not_books():
    role = POST.read_text(encoding="utf-8")
    hook = HOOK.read_text(encoding="utf-8")
    for src in (role, hook):
        assert "--post_name=statements" in src or "--name={{ item.slug }}" in src
        assert "statements" in src and "contact" in src
        assert "wp post create" in src
        for token in BOOK_WRITE_TOKENS:
            assert token not in src
