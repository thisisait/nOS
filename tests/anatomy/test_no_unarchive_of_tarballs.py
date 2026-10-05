"""Anatomy CI gate — no `unarchive` of a tarball.

`ansible.builtin.unarchive` needs GNU tar for .tar.gz; macOS ships bsdtar, so the
module falls back to unzip and fails ("Failed to find handler"). Backrest learned
it first; offline_maps relearned it on the 2026-10-03 converge. Use `tar -xzf`.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TARBALL = (".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tar")


def _tasks(node):
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always"):
            yield from _tasks(node.get(key))


def test_no_unarchive_of_a_tarball():
    bad = []
    for path in [*REPO.glob("roles/*/tasks/*.yml"), *REPO.glob("tasks/**/*.yml"), REPO / "main.yml"]:
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        for task in _tasks(doc):
            mod = task.get("ansible.builtin.unarchive") or task.get("unarchive")
            if isinstance(mod, dict) and str(mod.get("src", "")).split("?")[0].endswith(TARBALL):
                bad.append(f"{path.relative_to(REPO)}: {task.get('name')}")
    assert not bad, f"unarchive of a tarball fails on macOS (bsdtar) — use tar -xzf: {bad}"
