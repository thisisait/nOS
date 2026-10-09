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


_SERVICES_RE = re.compile(r"(\d+) (?:open-source|FOSS) services")


def test_readme_and_release_service_count_is_measured():
    """README.md and RELEASE.md say the same service count, and it is the
    manifest's. On 2026-10-09 README said 'about 55', RELEASE said '~50',
    the manifest held 74 rows — two moving counts, both stale."""
    import sys  # noqa: PLC0415
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity  # noqa: PLC0415 — the manifest reader, never a filename
    measured = len(nos_identity.services())
    claims = {}
    for doc in ("README.md", "RELEASE.md"):
        m = _SERVICES_RE.search((REPO / doc).read_text(encoding="utf-8"))
        assert m, f"{doc} must state '<N> open-source|FOSS services'"
        claims[doc] = int(m.group(1))
    assert set(claims.values()) == {measured}, (
        f"{claims} vs {measured} rows in state/manifest.yml (nos_identity.services())"
    )
