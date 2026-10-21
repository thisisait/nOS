"""Anatomy CI gate — active-work.md stays a pointer, not an archive.

Phase A of the devlog epic (2026-06-12) cut docs/active-work.md from 522
lines of archaeology to a NOW-only pointer; narrative history belongs in the
devlog (docs/devlog/README.md), completed plans in docs/archive/. This gate
pins the ceiling so the file cannot silently regress into a changelog.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
ACTIVE_WORK = REPO / "docs/active-work.md"
CEILING = 150


def test_active_work_under_ceiling():
    lines = ACTIVE_WORK.read_text(encoding="utf-8").count("\n")
    assert lines <= CEILING, (
        f"docs/active-work.md is {lines} lines (ceiling {CEILING}) — move the "
        "narrative to a devlog entry (/devlog new) and keep this file NOW-only"
    )


def test_active_work_points_at_the_devlog():
    text = ACTIVE_WORK.read_text(encoding="utf-8")
    assert "devlog" in text, "the pointer doctrine paragraph went missing"


# --- the projection (row active-work-from-table, rel-018) --------------------
# docs/active-work.md below its marker is tools/active-work-gen.py's output.
# Status lives only in the PRIVATE seed, so CI cannot hold the statuses; it can
# hold the shape and that every slug is a real one (state/roadmap/index.yml).


def _check(tools_dir: pathlib.Path, seed: pathlib.Path | None = None):
    env = dict(os.environ)
    if seed is not None:
        env["NOS_SEED_DIR"] = str(seed)
    return subprocess.run([sys.executable, str(tools_dir / "active-work-gen.py"), "--check"],
                          cwd=REPO, env=env, capture_output=True, text=True, timeout=120)


def test_active_work_is_what_the_roadmap_projects():
    got = _check(REPO / "tools")
    if got.returncode == 3:  # no seed here: the shape was held, the statuses were not
        pytest.skip(got.stdout.strip() or "roadmap seed unreachable: UNKNOWN")
    assert got.returncode == 0, (
        "docs/active-work.md is not what tools/active-work-gen.py writes — edit the "
        f"roadmap rows and rerun the writer, never the file:\n{(got.stdout + got.stderr)[-1500:]}")


def _scratch_repo(tmp_path: pathlib.Path, doc: str) -> pathlib.Path:
    for rel in ("tools/active-work-gen.py", "tools/roadmap_seed_lib.py", "state/roadmap/index.yml"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, tmp_path / rel)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/active-work.md").write_text(doc, encoding="utf-8")
    return tmp_path / "tools"


def test_without_the_seed_the_shape_is_still_held(tmp_path):
    """No seed (CI): the committed projection passes the offline half and says so."""
    tools = _scratch_repo(tmp_path, ACTIVE_WORK.read_text(encoding="utf-8"))
    got = _check(tools, seed=tmp_path / "no-seed")
    assert got.returncode == 3 and "shape holds" in got.stdout, (
        f"without the seed --check must still hold the shape, then say UNKNOWN:\n{got.stdout}{got.stderr}")


@pytest.mark.parametrize("line", ["- `no-such-row-ever` **next**", "- a hand-written note"])
def test_without_the_seed_a_hand_edit_is_red(tmp_path, line):
    text = ACTIVE_WORK.read_text(encoding="utf-8").rstrip("\n") + "\n" + line + "\n"
    got = _check(_scratch_repo(tmp_path, text), seed=tmp_path / "no-seed")
    assert got.returncode == 1, (
        f"a line below the marker that is not a real row's projection must be red offline:\n{got.stdout}")
