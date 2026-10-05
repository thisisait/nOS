"""Gate: the jsonschema dep-tree uninstall touches Homebrew's pip, nothing else.

2026-10-05: the task had no `executable`, so ansible.builtin.pip used the
interpreter Ansible runs under (pyenv 3.13) and removed jsonschema, referencing,
rpds-py and attrs from it on every converge; the anatomy suite failed to collect.
"""
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _tasks(node):
    if isinstance(node, list):
        for x in node:
            yield from _tasks(x)
    elif isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _tasks(v)


def test_every_pip_uninstall_names_its_pip():
    bad = []
    for t in _tasks(yaml.safe_load((REPO / "main.yml").read_text())):
        pip = t.get("ansible.builtin.pip")
        if isinstance(pip, dict) and pip.get("state") == "absent":
            exe = str(pip.get("executable", ""))
            if "homebrew_prefix" not in exe:
                bad.append(t.get("name"))
    assert not bad, f"pip uninstall without Homebrew's executable strips the operator's Python: {bad}"
