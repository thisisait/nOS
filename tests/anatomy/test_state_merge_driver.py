"""Anatomy CI gate — the derived graph artifacts carry the regen merge driver.

Parallel agents regenerate state/anatomy-graph.json (+ the face vendored
copy); a content merge of a derived artifact is noise, so .gitattributes marks
both `merge=regen` (keep ours, then regenerate — docs/adr/0002-graphify-borrowings.md §3, proven on a
synthetic conflict). Asked via `git check-attr`, the artifact, not the prose.
The authored night-watch.json must NOT be marked: expectations are merged,
never regenerated.
"""
from __future__ import annotations

import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]

DERIVED = [
    "state/anatomy-graph.json",
    "files/anatomy/face/src/lib/anatomy/anatomy-graph.json",
]
AUTHORED = ["state/night-watch.json"]


def _merge_attr(path: str) -> str:
    out = subprocess.run(["git", "check-attr", "merge", "--", path],
                         cwd=REPO, capture_output=True, text=True, check=True)
    return out.stdout.strip().rsplit(": ", 1)[-1]


def test_derived_artifacts_use_the_regen_driver():
    for path in DERIVED:
        assert _merge_attr(path) == "regen", (
            f"{path} lacks `merge=regen` in .gitattributes — a parallel-agent "
            "merge will conflict on a file whose only correct resolution is "
            "regeneration (docs/adr/0002-graphify-borrowings.md §3)")


def test_authored_state_is_not_swept_in():
    for path in AUTHORED:
        assert _merge_attr(path) != "regen", (
            f"{path} is AUTHORED, not derived — keep-ours would silently "
            "discard the other branch's expectations")
