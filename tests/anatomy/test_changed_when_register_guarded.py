"""Anatomy CI gate — register-guarded ``changed_when`` on skippable post tasks.

Finding ``changed-when-default-silent-success`` (v0.7): three post-task
``changed_when:`` expressions keyed a ``{{ _var | default(...) }}`` predicate
on a register variable whose owning task carries a ``when:`` block, so the
register can be undefined when the task is skipped. The ``default()`` then
silently substitutes a value, which is fragile copy-paste bait — a maintainer
who clones the line onto a task WITHOUT a ``when:`` inherits an indeterminate
``changed`` verdict. The structural fix gates each predicate on
``(_var is defined)`` so a skipped task deterministically reports
``changed=false`` regardless of the default.

This gate pins the three confirmed evidence sites so they cannot regress to the
bare-``default()`` shape:

  * roles/pazny.bluesky_pds/tasks/post.yml — ``_pds_pw_update``
  * roles/pazny.calibre_web/tasks/post.yml — ``_cw_pw_update``
  * roles/pazny.metabase/tasks/post.yml    — ``_mb_setup``

It is intentionally narrow — only the cited sites, byte-checked — so it cannot
drift into a sweeping style assertion over the whole tree.
"""

from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

# (relative path, register var, a substring of the ORIGINAL predicate that must
#  survive the guard so the fix is additive, not a rewrite).
CASES = [
    (
        "roles/pazny.bluesky_pds/tasks/post.yml",
        "_pds_pw_update",
        "_pds_pw_update.rc | default(1) == 0",
    ),
    (
        "roles/pazny.calibre_web/tasks/post.yml",
        "_cw_pw_update",
        "'UPDATED' in (_cw_pw_update.stdout | default(''))",
    ),
    (
        "roles/pazny.metabase/tasks/post.yml",
        "_mb_setup",
        "_mb_setup.status | default(0) == 200",
    ),
]


def _changed_when_lines(path: pathlib.Path) -> list[str]:
    return [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith("changed_when:")
    ]


@pytest.mark.parametrize("rel, var, predicate", CASES)
def test_changed_when_is_register_guarded(rel: str, var: str, predicate: str) -> None:
    path = REPO / rel
    assert path.is_file(), f"missing target file: {rel}"

    guard = f"{var} is defined"
    matches = [ln for ln in _changed_when_lines(path) if var in ln]
    assert matches, f"{rel}: no changed_when line references {var}"

    for line in matches:
        # The skip-safe guard must be present...
        assert guard in line, (
            f"{rel}: changed_when on {var} is not gated on '{guard}' "
            f"(false-success on a skipped task): {line!r}"
        )
        # ...and the original predicate must survive (fix is additive).
        assert predicate in line, (
            f"{rel}: original predicate dropped from {var} changed_when: {line!r}"
        )
