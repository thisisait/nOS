"""The cloud e2e lane (docs/cloud-e2e.md) keeps its promises offline.

A Claude cloud session is a disposable Ubuntu container with no systemd, no
$USER, a shared egress IP and a proxy that refuses Galaxy, ghcr blob storage,
quay.io and lscr.io. tools/cloud/ is the adapter; these gates pin the parts of
it that can silently rot without any sandbox present.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CLOUD = REPO / "tools" / "cloud"
PROFILE = REPO / "profiles" / "cloud-e2e.yml"

#: What the cloud sandbox's default egress policy refuses (measured 2026-09-25;
#: tools/cloud/registry-reach.py is the live probe). A service in the profile
#: pulling from one of these would make the lane red for a reason that is
#: about the network, not about nOS.
REFUSED_REGISTRIES = {"ghcr.io", "lscr.io", "quay.io"}


def _load_reach():
    spec = importlib.util.spec_from_file_location("registry_reach", CLOUD / "registry-reach.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_lock_pin_has_a_git_source():
    lock = yaml.safe_load((REPO / "requirements.lock.yml").read_text())
    src = yaml.safe_load((CLOUD / "galaxy-git-sources.yml").read_text())
    missing = [c["name"] for c in lock.get("collections", [])
               if c["name"] not in (src.get("collections") or {})]
    missing += [r["name"] for r in lock.get("roles", [])
                if r["name"] not in (src.get("roles") or {})]
    assert not missing, (
        f"requirements.lock.yml pins with no row in tools/cloud/galaxy-git-sources.yml: "
        f"{missing} — a cloud session cannot install them")


def test_git_install_plan_never_asks_galaxy_for_dependencies():
    """Every git install is --no-deps: resolving a galaxy.yml `dependencies:`
    block means calling Galaxy, which is the host the fallback exists to avoid."""
    p = subprocess.run(["python3", str(CLOUD / "galaxy-install.py"), "--source", "git", "--check"],
                       capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    installs = [ln for ln in p.stdout.splitlines() if "collection install" in ln]
    assert installs and all("--no-deps" in ln for ln in installs), p.stdout


def test_profile_flags_are_declared():
    """A typo in the profile (`install_postgres`) is a flag nothing reads."""
    sys_path = str(REPO / "tools")
    import sys
    sys.path.insert(0, sys_path)
    try:
        from nos_identity import resolve_flag  # noqa: PLC0415
    finally:
        sys.path.remove(sys_path)
    prof = yaml.safe_load(PROFILE.read_text())
    flags = [k for k in prof if k.startswith(("install_", "configure_")) or k == "redis_docker"]
    roles_defaults = "\n".join(p.read_text() for p in REPO.glob("roles/*/defaults/main.yml"))
    undeclared = [f for f in flags
                  if not resolve_flag(f) and not re.search(rf"^{f}:", roles_defaults, re.M)]
    assert not undeclared, f"profiles/cloud-e2e.yml sets undeclared flags: {undeclared}"


def test_profile_pulls_nothing_the_sandbox_refuses():
    reach = _load_reach()
    vars_ = reach.load(REPO / "default.config.yml")
    vars_.update(reach.load(REPO / "default.credentials.yml"))
    vars_.update(reach.load(PROFILE))
    top = reach.Resolver(vars_)
    bad = []
    for row in yaml.safe_load((REPO / "state" / "manifest.yml").read_text())["services"]:
        flag, role = row.get("install_flag"), REPO / "roles" / f"pazny.{row['id']}"
        if not flag or not role.is_dir() or not reach.truthy(top.value(flag)):
            continue
        local = reach.load(role / "defaults" / "main.yml")
        local.update(vars_)
        r = reach.Resolver(local)
        for tpl in role.glob("templates/compose*.j2"):
            for expr in reach.IMAGE_RE.findall(tpl.read_text()):
                img = str(r.render(expr.strip().strip("\"'")) or expr)
                if reach.registry_of(img) in REFUSED_REGISTRIES:
                    bad.append(f"{row['id']}: {img}")
    assert not bad, (
        "profiles/cloud-e2e.yml enables services whose image the cloud sandbox "
        f"cannot pull: {bad}. Point the role's *_image var at a Docker Hub "
        "mirror of the same image (see authentik_image), or leave the service off.")


def test_profile_does_not_install_into_the_controller():
    """The playbook's global pip task runs whichever `pip3` is first on PATH.
    MEASURED: with the frozen venv first it installed `ansible` there and moved
    ansible-core 2.21.0 → 2.21.4 mid-run. e2e.sh takes the venv off PATH; the
    profile also asks for nothing."""
    prof = yaml.safe_load(PROFILE.read_text())
    assert prof.get("pip_packages") == [], "cloud profile must set pip_packages: []"
    e2e = (CLOUD / "e2e.sh").read_text()
    assert "grep -v '/.ci-venv/bin'" in e2e


def test_e2e_refuses_removal_tokens():
    for tok in ("remove=data", "confirm=true", "blank=true", "flush=deep", "uninstall=true"):
        p = subprocess.run(["bash", str(CLOUD / "e2e.sh"), "converge", "-e", tok],
                           capture_output=True, text=True, timeout=60,
                           env={**os.environ, "PATH": os.environ.get("PATH", "")})
        assert p.returncode == 2, (tok, p.stdout, p.stderr)
        assert "refused" in p.stdout


def test_e2e_reset_refuses_a_machine_nobody_declared_disposable():
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_REMOTE", "NOS_E2E_SANDBOX")}
    p = subprocess.run(["bash", str(CLOUD / "e2e.sh"), "reset"], capture_output=True,
                       text=True, timeout=60, env=env)
    assert p.returncode == 2 and "refused" in p.stdout


def test_no_playbook_code_reads_USER_from_the_environment():
    """A container sets no $USER (measured: the cloud sandbox). ansible_facts
    user_id / user_gid come from the passwd database and always exist."""
    pat = re.compile(r"""env'\]\['USER'\]|ansible_env\.USER|lookup\(\s*'env'\s*,\s*'USER'\s*\)""")
    hits = []
    for base in ("roles", "tasks", "templates", "files/anatomy/plugins"):
        for p in (REPO / base).rglob("*"):
            if p.suffix in (".yml", ".yaml", ".j2") and p.is_file():
                for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                    if pat.search(line.split("#", 1)[0]):
                        hits.append(f"{p.relative_to(REPO)}:{n}")
    assert not hits, hits


def test_session_start_hook_is_registered_and_remote_only():
    settings = json.loads((REPO / ".claude" / "settings.json").read_text())
    cmds = [h["command"] for grp in settings["hooks"]["SessionStart"] for h in grp["hooks"]]
    assert any("session-start.sh" in c for c in cmds)
    hook = (REPO / ".claude" / "hooks" / "session-start.sh").read_text()
    assert 'CLAUDE_CODE_REMOTE:-}" != "true"' in hook, "hook must no-op outside the cloud"
    assert "tools/cloud/bootstrap.sh" in hook
    assert os.access(REPO / ".claude" / "hooks" / "session-start.sh", os.X_OK)


def test_preflight_throwaway_is_emptied():
    """The YAML-validation loop leaves the LAST file it loaded in
    `_preflight_throwaway`. On a checkout without config.yml that was
    default.credentials.yml, whose unrendered templates then aborted core-up's
    eager `{{ vars }}` snapshot — a fresh clone could not converge."""
    main = (REPO / "main.yml").read_text()
    loop = main.index('name: "_preflight_throwaway"')
    reset = main.find("_preflight_throwaway: {}", loop)
    snapshot = main.find("tasks/stacks/core-up.yml", loop)
    assert loop < reset < snapshot, "the throwaway must be emptied before core-up"


def test_an_empty_stack_is_not_brought_up():
    """`iiab` is always in _remaining_stacks; with nothing enabled there,
    `docker compose up` exits 1 ("no service selected") and the fail-fast
    assert failed a converge that had nothing to start (cloud profile,
    2026-09-25). Compose-up loops read _up_stacks; host-organ post gates keep
    reading _remaining_stacks."""
    up = (REPO / "tasks" / "stacks" / "stack-up.yml").read_text()
    drop = up.index("_up_stacks: \"{{ _remaining_stacks | select('in'")
    fire = up.index("Fire docker compose up -d per stack")
    assert drop < fire
    tail = up[fire:]
    assert 'loop: "{{ _remaining_stacks }}"' not in tail, "compose-up must loop _up_stacks"
    assert "'iiab' in (_remaining_stacks" in tail, "host-organ post gates must not lose iiab"


def test_apps_skip_reaches_the_renderer():
    """The discovery `find` only answers "any manifests?"; nos_apps_render
    lists apps_dir itself. A skip wired into the find alone rendered the app
    anyway (measured: twofauth kept coming up after apps_skip: [twofauth])."""
    role = (REPO / "roles/pazny.apps_runner/tasks/main.yml").read_text()
    assert 'skip: "{{ apps_skip | default([]) }}"' in role
    mod = (REPO / "files/anatomy/library/nos_apps_render.py").read_text()
    assert 'p["skip"]' in mod


def test_duplicated_blueprints_render_with_the_loaders_whitespace():
    """00-admin-groups and 30-agent-clients are written twice per converge —
    by the role (Ansible template, trim_blocks ON by default) and by the
    authentik-base plugin loader (plain Jinja, trim_blocks OFF). Identical
    templates, different bytes: each writer undid the other on every run."""
    import yaml as _y
    tasks = _y.safe_load((REPO / "roles/pazny.authentik/tasks/blueprints.yml").read_text())
    renders = [t["ansible.builtin.template"] for t in tasks if "ansible.builtin.template" in t]
    assert renders and all(r.get("trim_blocks") is False for r in renders)
    assert all(r.get("mode") == "0600" for r in renders), "SEC-1 mode, as the loader writes"
