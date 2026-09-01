"""Anatomy CI gate — a declared toggle must gate something.

MEASURED 2026-09-01: 2 of 93 install_*/configure_* flags had no consumer.
`install_cask_apps` was rendered as a toggle in docs/index.html while the cask
loop ran unconditionally; `install_engineering_apps` named three CAD apps that
had no cask list. Both closed — the first `when:`-gated, the second deleted.

A consumer is any mention outside default.config.yml, config.yml, docs/ and
tests/. Those four are excluded because a doc that ADVERTISES a flag and a
fixture that SETS it are what made these two look alive.
"""

from __future__ import annotations

import collections
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
CONFIG = REPO / "default.config.yml"

SKIP_DIRS = {".git", "node_modules", "docs", "tests", ".ci-venv", "dist",
             "vendor", ".svelte-kit", ".pytest_cache", "__pycache__"}
SKIP_FILES = {"default.config.yml", "config.yml"}
READ_SUFFIXES = {".yml", ".yaml", ".j2", ".py", ".sh", ".php", ".ts", ".js",
                 ".json", ".html", ".md", ""}


def _flags() -> list[str]:
    txt = CONFIG.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"^(install_[a-z0-9_]+|configure_[a-z0-9_]+):",
                                 txt, re.M)))


def _consumers() -> collections.Counter:
    flags = _flags()
    seen = collections.Counter()
    for p in REPO.rglob("*"):
        if not p.is_file() or p.suffix not in READ_SUFFIXES:
            continue
        if p.name in SKIP_FILES or any(s in p.parts for s in SKIP_DIRS):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for f in flags:
            if f in text:
                seen[f] += 1
    return seen


def test_the_sweep_reads_the_config_and_the_tree():
    """Positive control. An empty flag list or an empty walk makes the gate
    below vacuous, which is the failure mode of every scanner in this estate."""
    flags = _flags()
    assert len(flags) > 50, (
        f"only {len(flags)} toggles parsed from default.config.yml; the regex "
        "has stopped matching and this gate is blind")
    seen = _consumers()
    assert sum(seen.values()) > 200, (
        f"the tree walk found only {sum(seen.values())} references across "
        f"{len(flags)} flags; the walk is not reaching the roles")


def test_no_toggle_is_a_promise_with_nothing_behind_it():
    seen = _consumers()
    dead = [f for f in _flags() if seen[f] == 0]
    assert not dead, (
        f"{len(dead)} toggle(s) in default.config.yml gate nothing. Setting "
        f"one changes no behaviour, while the config — and possibly "
        f"docs/index.html — presents it as a choice:\n  " + "\n  ".join(dead)
        + "\n\nEither gate something on it (a `when:` is usually enough) or "
          "delete it. install_cask_apps was the first kind, "
          "install_engineering_apps the second.")
