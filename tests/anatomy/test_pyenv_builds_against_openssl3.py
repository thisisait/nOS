"""pyenv must build Python against OpenSSL 3, never whatever `openssl` means today.

Measured 2026-10-11 on the release PR's macos-26 runner: Homebrew's `openssl`
now resolves to openssl@4 (4.0.3). python-build 2.8.9 tries openssl@1.1, then
openssl@3, then falls back to `openssl`. The runner had no openssl@3, so
Python 3.13.16 built against OpenSSL 4, `_ssl` did not compile, and
`pyenv install` failed (BUILD FAILED, `cannot stat _ssl.cpython-313-darwin.so`).
A fresh Mac is the same machine.

Pinned: tasks/python.yml installs openssl@3 and tells python-build to use it.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TASKS = REPO / "tasks/python.yml"
FORMULA = "openssl@3"


def _tasks() -> list[dict]:
    return yaml.safe_load(TASKS.read_text(encoding="utf-8")) or []


def test_openssl3_is_installed_with_the_build_deps():
    deps = next(t for t in _tasks() if "community.general.homebrew" in t
                and "pyenv" in t["community.general.homebrew"]["name"])
    assert FORMULA in deps["community.general.homebrew"]["name"], (
        f"{FORMULA} is not among pyenv's build deps; a runner or fresh Mac with "
        "only openssl@4 builds Python without _ssl")


def test_the_install_pins_python_build_to_openssl3():
    install = next(t for t in _tasks()
                   if "pyenv install" in str(t.get("ansible.builtin.shell", "")))
    env = install.get("environment") or {}
    assert env.get("PYTHON_BUILD_HOMEBREW_OPENSSL_FORMULA") == FORMULA, (
        "pyenv install does not set PYTHON_BUILD_HOMEBREW_OPENSSL_FORMULA to "
        f"{FORMULA}; python-build falls back to `openssl`, which is openssl@4")
