"""Host-Python tasks run the configured interpreter, not the repo's CI pin.

``tasks/python.yml`` installs ``python_version`` and sets it as pyenv's
global. The playbook runs with the repo as cwd, and the repo root carries a
``.python-version`` (the frozen CI toolchain), which outranks ``pyenv
global``. On a fresh Mac ``pyenv exec pip`` then asked for the CI patch
release, which was never installed, and the first install failed at
"Upgrade pip" (thisisait/nOS#37).

``PYENV_VERSION`` outranks every version file, so each ``pyenv exec`` task
must set it to ``python_version``.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TASKS = REPO / "tasks/python.yml"


def _pyenv_exec_tasks():
    for task in yaml.safe_load(TASKS.read_text(encoding="utf-8")) or []:
        script = task.get("ansible.builtin.shell") or task.get("shell") or ""
        if "pyenv exec" in str(script):
            yield task


def test_there_are_pyenv_exec_tasks():
    assert list(_pyenv_exec_tasks()), "gate went blind: no `pyenv exec` task found"


def test_every_pyenv_exec_task_pins_pyenv_version():
    unpinned = [
        t["name"]
        for t in _pyenv_exec_tasks()
        if "python_version" not in str((t.get("environment") or {}).get("PYENV_VERSION", ""))
    ]
    assert not unpinned, (
        f"{unpinned}: set environment.PYENV_VERSION to python_version, or the "
        "repo's .python-version (CI pin) decides which interpreter runs"
    )
