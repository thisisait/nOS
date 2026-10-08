"""The Homebrew install cap holds on a stock Mac, where there is no `timeout`.

The cask and formula install loops capped each ``brew install`` with
``timeout 90`` / ``timeout 120`` behind ``command -v timeout``. Stock macOS
ships no ``timeout`` (it comes with coreutils, installed later by this very
role), so on a first install the cap silently fell away: one unreachable
download host held a single cask for 10 minutes before failing the play.

This gate renders each install script and runs it against a ``brew`` that
hangs, on a PATH with no ``timeout``/``gtimeout``. The script must return
the TIMEOUT verdict within the cap, not wait for brew.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import time

import jinja2
import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TASK = REPO / "roles/pazny.mac.homebrew/tasks/main.yml"
DEFAULTS = REPO / "roles/pazny.mac.homebrew/defaults/main.yml"

LOOPS = {
    "Install configured cask applications.": "homebrew_cask_install_timeout",
    "Ensure configured homebrew packages are installed.": "homebrew_formula_install_timeout",
}


def _tasks(node):
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item)
    elif isinstance(node, dict):
        if "name" in node:
            yield node
        for key in ("block", "rescue", "always"):
            if key in node:
                yield from _tasks(node[key])


def _script(name: str) -> str:
    for task in _tasks(yaml.safe_load(TASK.read_text(encoding="utf-8"))):
        if task.get("name") == name:
            return task["ansible.builtin.shell"]
    raise AssertionError(f"task {name!r} not found in {TASK}")


def _bare_path(tmp: pathlib.Path) -> str:
    """A PATH with a hanging fake brew and only the tools the scripts need."""
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    brew = bin_dir / "brew"
    brew.write_text("#!/bin/bash\nsleep 30\n", encoding="utf-8")
    brew.chmod(0o755)
    for tool in ("sleep", "grep", "cat"):
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    return str(bin_dir)


@pytest.mark.parametrize("task_name,cap_var", sorted(LOOPS.items()))
def test_cap_var_has_a_role_default(task_name, cap_var):
    defaults = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))
    assert isinstance(defaults.get(cap_var), int), f"{cap_var} needs an int default"
    assert "{{ " + cap_var + " }}" in _script(task_name)


@pytest.mark.parametrize("task_name,cap_var", sorted(LOOPS.items()))
def test_hanging_brew_is_cut_without_coreutils(tmp_path, task_name, cap_var):
    path = _bare_path(tmp_path)
    assert shutil.which("timeout", path=path) is None
    assert shutil.which("gtimeout", path=path) is None

    script = jinja2.Environment().from_string(_script(task_name)).render(
        item="fixture-pkg",
        homebrew_prefix=str(tmp_path / "prefix"),
        homebrew_cask_appdir=str(tmp_path / "Applications"),
        **{cap_var: 1},
    )
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["/bin/bash", "-c", script],
            env={"PATH": path, "HOME": str(tmp_path)},
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{task_name}: no cap without `timeout` — waited for the hung brew")
    elapsed = time.monotonic() - started

    assert elapsed < 8, f"{task_name}: took {elapsed:.1f}s with a 1s cap"
    assert "TIMEOUT:" in proc.stdout, proc.stdout + proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr
