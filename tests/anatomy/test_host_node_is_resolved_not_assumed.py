"""Host-side `node` calls use a resolved binary, never PATH's luck.

nOS installs Node through nvm (tasks/node.yml); Homebrew has no `node` on a
fresh Mac. pazny.keap ran ``argv: [node, …]`` with PATH = Homebrew's bin, so
the self-model WET GATE died with "No such file or directory: b'node'" on a
first install (thisisait/nOS#50). It only worked where something else had
pulled Homebrew node in.

pazny.cortex already resolves Node via nvm into a fact. Every host command
whose argv starts with a bare ``node`` must do the same.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROOTS = [REPO / "roles", REPO / "tasks"]


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _bare_node_calls():
    for root in ROOTS:
        for path in sorted(root.rglob("*.yml")):
            if "/templates/" in str(path) or "/files/" in str(path):
                continue
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue
            for node in _walk(doc):
                cmd = node.get("ansible.builtin.command") or node.get("command")
                if isinstance(cmd, dict) and isinstance(cmd.get("argv"), list) and cmd["argv"]:
                    if str(cmd["argv"][0]).strip() == "node":
                        yield f"{path.relative_to(REPO)}: {node.get('name')}"


def test_no_host_command_runs_bare_node():
    offenders = list(_bare_node_calls())
    assert not offenders, (
        "argv[0] is a bare `node` — resolve it via nvm like pazny.cortex "
        "(_cortex_node_bin) instead:\n  " + "\n  ".join(offenders)
    )
