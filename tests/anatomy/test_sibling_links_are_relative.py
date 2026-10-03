"""Anatomy CI gate — a symlink to its own sibling is relative.

MEASURED 2026-10-03: maps_cache_dir/fonts -> /Volumes/.../maps/ofm. The cache
is bind-mounted into tileserver at /cache, where that absolute target does not
exist; the container restarted 33 times and failed the converge health-wait.
"""
from __future__ import annotations

import pathlib
import posixpath

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _tasks(node):
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always"):
            yield from _tasks(node.get(key))


def test_a_link_beside_its_target_is_relative():
    bad = []
    for path in sorted((REPO / "roles").glob("*/tasks/*.yml")) + sorted((REPO / "tasks").rglob("*.yml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        for task in _tasks(doc):
            args = task.get("ansible.builtin.file") or task.get("file")
            if not isinstance(args, dict) or args.get("state") != "link":
                continue
            src, dest = str(args.get("src", "")), str(args.get("dest") or args.get("path") or "")
            if src.startswith(("/", "{{")) and posixpath.dirname(src) == posixpath.dirname(dest):
                bad.append(f"{path.relative_to(REPO)}: {task.get('name')}")
    assert not bad, f"sibling symlink with an absolute target (breaks under a bind mount): {bad}"
