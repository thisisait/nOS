"""Anatomy CI gate — README.md role count stays honest.

README.md line 6 (the first prose a new user reads) advertises the number of
Ansible roles the playbook orchestrates ("orchestrates N roles"). It drifted
silently as roles were added — it claimed 45+ while 71 roles/pazny.*
directories existed on disk. CLAUDE.md line 84 already states the true 71; the
README understated capability by ~26 roles. No gate caught it.

This pins the prose to ground truth: the count README prints must equal the
number of roles on disk (one per roles/pazny.<service>/).
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLES_ROOT = REPO / "roles"
README = REPO / "README.md"

_COUNT_RE = re.compile(r"orchestrates (\d+)\+? roles")


def _filesystem_count() -> int:
    # Count SERVICE roles only. `pazny._*` (underscore-prefixed) dirs are private
    # shared-task libraries — e.g. pazny._common_tasks/tasks/wait_for_api.yml —
    # not services, never invoked standalone, so they don't count toward the
    # "orchestrates N roles" service tally the README advertises.
    return sum(
        1
        for d in ROLES_ROOT.iterdir()
        if d.is_dir()
        and d.name.startswith("pazny.")
        and not d.name.startswith("pazny._")
    )


def test_readme_role_count_is_accurate():
    """README.md line 6's role count == the real roles/pazny.* count."""
    text = README.read_text(encoding="utf-8")
    m = _COUNT_RE.search(text)
    assert m, "README.md must state 'orchestrates <N> roles'"
    claimed = int(m.group(1))
    actual = _filesystem_count()
    assert claimed == actual, (
        f"README.md claims {claimed} roles but {actual} roles/pazny.* "
        f"directories exist under {ROLES_ROOT.relative_to(REPO)}/"
    )
