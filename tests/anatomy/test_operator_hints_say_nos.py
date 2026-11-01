"""What a converge tells the operator to run next is `nos …`, never `ansible-playbook main.yml`.

2026-11-01: the Santa role stopped with "Re-run: ansible-playbook main.yml --tags santa".
On the estate that asks for sudo twice (-K plus the one-stop prompt) and an Enter at the
second breaks it (memory: converge-via-nos-wrapper); the estate also runs from its own
clone, not from wherever the operator stands. Parsed, not grepped: comments are for
developers and drop out with YAML; every string a task carries is what the operator reads.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
# (file) -> why it may still name ansible-playbook
ALLOWED = {
    "tasks/run-mode.yml": "it repairs the nos CLI itself; while nos is broken, ansible-playbook is the way",
}


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for x in node:
            yield from _strings(x)
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)


def _files():
    yield REPO / "main.yml"
    yield from (REPO / "tasks").rglob("*.yml")
    for sub in ("tasks", "handlers"):
        yield from (REPO / "roles").glob(f"*/{sub}/**/*.yml")


def test_operator_hints_say_nos():
    seen, bad = 0, []
    for f in _files():
        rel = str(f.relative_to(REPO))
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        for s in _strings(doc):
            seen += 1
            if "ansible-playbook main.yml" in s and rel not in ALLOWED:
                bad.append(f"{rel}: {s.strip().splitlines()[0][:90]}")
    assert seen > 1000, f"the scan lost the tree: {seen} strings"
    assert not bad, "tell the operator `nos --tags …`, not ansible-playbook:\n" + "\n".join(bad)
