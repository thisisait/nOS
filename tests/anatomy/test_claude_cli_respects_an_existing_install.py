"""A `claude` that already resolves is the operator's; a converge leaves it alone.

Review 2026-10-05: the operator kept collecting Claude Code installs. With a
claude already on PATH, tasks/claude-cli.yml still ran `claude install stable`
(a second, native copy), force-linked {{ homebrew_prefix }}/bin/claude over
whatever was there, and prepended ~/.local/bin in ~/.zshrc. Runs the real task
file through Ansible in a temp HOME on a sealed PATH; every installer is a stub.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "tasks/claude-cli.yml"
TOGGLE = "install_claude_cli_vendor"
needs_ansible = pytest.mark.skipif(importlib.util.find_spec("ansible") is None, reason="runs the task through real Ansible")
# Logs its own name + args and exits; nothing here may ever run during the gate.
STUB = '#!/bin/sh\necho "$(basename "$0") $*" >> "{log}"\nexit 0\n'


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and not p.is_symlink() and p.name != "calls.log"}


def _exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


def _converge(tmp: Path, existing: Path | None, native: bool, **extra) -> tuple[dict, dict, str, str]:
    home, stubs, brew = tmp / "home", tmp / "stubs", tmp / "brew"
    for d in (home, stubs, brew / "bin"):
        d.mkdir(parents=True, exist_ok=True)
    log = tmp / "calls.log"
    log.touch()
    for name in ("curl", "wget", "npm", "npx", "brew"):
        _exe(stubs / name, STUB.format(log=log))
    if native:  # the vendor's own native build, already present
        _exe(home / ".local/bin/claude", STUB.format(log=log))
    if existing:
        _exe(existing, STUB.format(log=log) + "# operator's own copy\n")
    before = _snapshot(tmp)

    play = [{"hosts": "localhost", "connection": "local", "gather_facts": True, "gather_subset": ["!all", "min"],
             "vars": {"ansible_python_interpreter": sys.executable,
                      "nos_pkg_manager": "homebrew", "homebrew_prefix": str(brew), **extra},
             "tasks": [{"import_tasks": str(TASKS)}]}]
    (tmp / "play.yml").write_text(yaml.safe_dump(play))
    # Sealed PATH: the host's own claude/curl/npm/brew can never be reached.
    path = ":".join([str(existing.parent)] if existing else []) + f":{stubs}:/usr/bin:/bin:/usr/sbin:/sbin"
    env = {**os.environ, "HOME": str(home), "PATH": path.lstrip(":"), "ANSIBLE_LOCAL_TEMP": str(tmp / ".ansible")}
    r = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(tmp / "play.yml")],
                       capture_output=True, text=True, cwd=tmp, env=env, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-1000:]
    return before, _snapshot(tmp), log.read_text(), r.stdout


@needs_ansible
@pytest.mark.parametrize("native", [False, True], ids=["no-native-build", "native-build-present"])
@pytest.mark.parametrize("where", ["bin", "brew/bin"], ids=["on-path", "in-brew-prefix"])
def test_an_existing_claude_is_left_alone(tmp_path, where, native):
    existing = tmp_path / where / "claude"
    before, after, calls, out = _converge(tmp_path, existing, native)
    gone = sorted(set(before) - set(after))
    changed = sorted(k for k in before if k in after and before[k] != after[k])
    assert not gone, f"the converge removed files it did not create: {gone}"
    assert not changed, f"the converge rewrote files it did not create: {changed}"
    assert existing.is_file() and not existing.is_symlink(), f"{existing} was replaced"
    assert not calls.strip(), f"an installer ran although a claude was already there:\n{calls}"
    assert not (tmp_path / "home/.zshrc").exists(), "~/.zshrc was edited to re-order the operator's PATH"
    assert str(existing) in out, "the run did not report which claude it found"


def _declared_default(name: str):
    """The default as default.config.yml declares it, not as the task guesses it."""
    return yaml.safe_load((REPO / "default.config.yml").read_text())[name]


@needs_ansible
def test_no_claude_anywhere_installs_nothing_by_default(tmp_path):
    """The vendor script is downloaded and run only on the operator's word."""
    default = _declared_default(TOGGLE)
    assert default is False, f"{TOGGLE} must default to false, got {default!r}"
    _, _, calls, out = _converge(tmp_path, None, native=False, **{TOGGLE: default})
    assert not calls.strip(), f"an installer ran without {TOGGLE}:\n{calls}"
    assert f"set {TOGGLE}: true" in out, "absence must be reported with the switch that ends it"


@needs_ansible
def test_the_toggle_runs_only_the_vendor_installer_once(tmp_path):
    """Positive control: a gate that passes because nothing ever installs is blind."""
    _, _, calls, out = _converge(tmp_path, None, native=False, **{TOGGLE: True})
    assert [c.split()[0] for c in calls.splitlines()] == ["curl"], f"expected one vendor installer call:\n{calls}"
    assert "claude.ai/install.sh" in calls
    assert "NO claude found" in out, "a failed install must be reported as absence, not success"
