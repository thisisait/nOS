"""Agents' claude runs as its own macOS user, never with bypassPermissions.

Row agent-runtime-least-privilege (epic workload-allowlist): agents were the
operator's claude CLI with `--permission-mode bypassPermissions` and ~/.nos
readable, so one Bash call read every secret. pazny.mac.agent_user renders a
launcher, a wrapper and a sudoers rule; every claim here is against the
RENDERED artifact — the launcher is executed, the sudoers file goes through
`visudo -cf`, the plists through plistlib.
"""

from __future__ import annotations

import getpass
import os
import plistlib
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "roles" / "pazny.mac.agent_user"
CONFIG = yaml.safe_load((REPO / "default.config.yml").read_text())


def _env() -> jinja2.Environment:
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined, keep_trailing_newline=True)
    env.filters["bool"] = lambda v: str(v).strip().lower() in ("1", "true", "yes", "on")
    env.filters["quote"] = lambda v: shlex.quote(str(v))
    env.filters["dirname"] = lambda v: os.path.dirname(str(v))
    return env


def _vars(**over) -> dict:
    """Role defaults + the shared keys from default.config.yml, resolved like Ansible."""
    ctx = {k: v for k, v in CONFIG.items() if k.startswith("agents_")}
    ctx.update(yaml.safe_load((ROLE / "defaults" / "main.yml").read_text()))
    ctx.update(ansible_facts={"user_id": "operator", "env": {"HOME": "/Users/operator"}})
    ctx.update(over)
    env = _env()
    for _ in range(4):  # nested {{ }} in defaults
        ctx = {k: (yaml.safe_load(env.from_string(v).render(ctx)) if isinstance(v, str) and "{{" in v
                   else [env.from_string(i).render(ctx) if isinstance(i, str) else i for i in v]
                   if isinstance(v, list) else v)
               for k, v in ctx.items()}
    return ctx


def _render(template: Path, ctx: dict) -> str:
    return _env().from_string(template.read_text()).render(ctx)


@pytest.fixture
def launcher(tmp_path):
    """The launcher rendered for THIS user, with a fake claude that prints its argv."""
    libexec, wt, home = tmp_path / "libexec", tmp_path / "wt", tmp_path / "home"
    for d in (libexec, wt, home):
        d.mkdir()
    fake = libexec / "claude"
    fake.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n')
    fake.chmod(0o755)
    secret = tmp_path / "secrets.yml"
    secret.write_text("x: 1\n")
    ctx = _vars(agents_user=getpass.getuser(), agents_libexec_dir=str(libexec),
                agents_worktrees_dir=str(wt), agents_user_home=str(home),
                agents_forbidden_paths=[str(secret), str(tmp_path / "absent")])
    script = tmp_path / "claude-as-agent"
    script.write_text(_render(ROLE / "templates" / "claude-as-agent.sh.j2", ctx))
    script.chmod(0o755)
    return script, secret, ctx


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(script), *args], capture_output=True, text=True, timeout=20)


CALLER = ("--print", "--output-format", "json", "--permission-mode", "bypassPermissions",
          "--", "-starts with a dash")


def test_a_readable_secret_refuses_the_run(launcher):
    script, _secret, _ = launcher
    out = _run(script, *CALLER)
    assert out.returncode == 2 and "REFUSING" in out.stderr, (
        "the launcher started claude while the operator's secrets file was readable "
        f"by the agent user (rc={out.returncode}, stdout={out.stdout[:200]!r})")


def test_an_unreadable_secret_runs_with_dont_ask_and_the_allow_list(launcher):
    script, secret, ctx = launcher
    secret.chmod(0o000)
    try:
        out = _run(script, *CALLER)
    finally:
        secret.chmod(0o600)
    assert out.returncode == 0, out.stderr
    argv = out.stdout.splitlines()
    assert "bypassPermissions" not in argv, "the caller's bypassPermissions reached claude"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--allowed-tools") + 1] == ",".join(ctx["agents_allowed_tools"])
    assert argv[argv.index("--add-dir") + 1] == ctx["agents_worktrees_dir"]
    assert argv[-2:] == ["--", "-starts with a dash"], "the prompt lost its `--` guard"


@pytest.mark.parametrize("flag", ["--dangerously-skip-permissions", "--add-dir", "--allowedTools"])
def test_a_caller_cannot_widen_the_permissions(launcher, flag):
    script, secret, _ = launcher
    secret.unlink()
    assert _run(script, "--print", flag, "/").returncode == 2


def test_the_wrong_user_is_refused(tmp_path):
    ctx = _vars(agents_user="nobody-else", agents_forbidden_paths=[])
    script = tmp_path / "l"
    script.write_text(_render(ROLE / "templates" / "claude-as-agent.sh.j2", ctx))
    script.chmod(0o755)
    assert _run(script, "--print").returncode == 2


def test_forbidden_paths_name_the_secrets_file():
    paths = _vars()["agents_forbidden_paths"]
    assert "/Users/operator/.nos/secrets.yml" in paths and "/Users/operator/.nos" in paths


@pytest.mark.skipif(not shutil.which("visudo"), reason="visudo not installed")
def test_sudoers_validates_and_grants_exactly_the_launcher(tmp_path):
    ctx = _vars()
    text = _render(ROLE / "templates" / "nos-agent.sudoers.j2", ctx)
    f = tmp_path / "nos-agent"
    f.write_text(text)
    chk = subprocess.run(["visudo", "-cf", str(f)], capture_output=True, text=True)
    assert chk.returncode == 0, chk.stdout + chk.stderr
    rules = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith(("#", "Defaults"))]
    assert rules == [f"operator ALL=({ctx['agents_user']}) NOPASSWD: {ctx['agents_launcher']}"], rules
    keep = re.search(r'env_keep = "([^"]*)"', text).group(1).split()
    assert keep == ctx["agents_env_keep"]
    leaked = [k for k in keep if re.search(r"CLIENT_SECRET|PASSWORD|_KEY$|BONE_SECRET", k)]
    assert not leaked, f"sudo would carry {leaked} into the agent"
    assert "env_reset" in text and "SETENV" not in text


def test_the_user_is_neither_admin_nor_staff():
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    user = next(t["ansible.builtin.user"] for t in tasks if "ansible.builtin.user" in t)
    assert user["group"] == "{{ agents_user }}" and user["groups"] == [] and user["append"] is False
    verify = [t for t in tasks if "verify" in t.get("tags", [])]
    probe = next(t for t in verify if "/bin/test" in t.get("ansible.builtin.command", {}).get("argv", []))
    assert probe["loop"] == "{{ agents_forbidden_paths }}" and probe["failed_when"] == "agents_read_probe.rc == 0"


@pytest.mark.parametrize("plist", ["pazny.wing/templates/wing.plist.j2", "pazny.pulse/templates/pulse.plist.j2"])
def test_nothing_changes_until_the_flag_flips(plist):
    tpl = REPO / "roles" / plist
    off = plistlib.loads(_render(tpl, _vars(agents_separate_user=False)).encode())
    on = plistlib.loads(_render(tpl, _vars(agents_separate_user=True)).encode())
    assert "NOS_CLAUDE_BIN" not in off["EnvironmentVariables"]
    assert on["EnvironmentVariables"]["NOS_CLAUDE_BIN"] == "/usr/local/libexec/nos-agent/nos-agent-claude"


def test_the_flag_ships_off():
    assert CONFIG["agents_separate_user"] is False
