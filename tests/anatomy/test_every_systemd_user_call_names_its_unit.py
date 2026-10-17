"""Every include of pazny.linux.systemd_user passes the inputs its ensure_unit asserts.

All-on (ubuntu-24.04) on release PR #58 died in '[systemd_user] Assert required inputs'
(su_name is defined): pazny.backrest passed su_unit_name, a name the role never reads, so on
Linux Backrest never got its unit. The role's own header lists the required inputs.
"""

from __future__ import annotations

import glob
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
REQUIRED = ("su_name", "su_description")


def _calls():
    for f in sorted(glob.glob(str(REPO / "roles/*/tasks/**/*.yml"), recursive=True)) + [str(REPO / "main.yml")]:
        try:
            doc = yaml.safe_load(Path(f).read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue

        def walk(n):
            if isinstance(n, list):
                for x in n:
                    yield from walk(x)
            elif isinstance(n, dict):
                inc = n.get("ansible.builtin.include_role") or n.get("include_role") or {}
                if isinstance(inc, dict) and inc.get("name") == "pazny.linux.systemd_user":
                    yield f, n.get("name"), n.get("vars") or {}
                for k in ("block", "rescue", "always", "tasks", "pre_tasks", "post_tasks"):
                    yield from walk(n.get(k))
        yield from walk(doc)


def test_every_call_passes_the_required_inputs():
    calls = list(_calls())
    assert calls, "no systemd_user include found: re-point this gate"
    bad = [f"{Path(f).relative_to(REPO)}: {name!r} lacks {[r for r in REQUIRED if r not in v]}"
           for f, name, v in calls if any(r not in v for r in REQUIRED)]
    assert not bad, "the role asserts these inputs; a missing one fails the Linux converge:\n" + "\n".join(bad)
