"""dtt-capture writes a valid per-row seed file, and refuses one that would fail.

The machinery behind the dtt-capture skill (operator directive: ideas/plans/specs
are defined via skill + dtt, not docs/*.md). It must write THROUGH the loader's
rules — a captured file the seeder would choke on is worse than no capture — so
this drives the tool against a scratch NOS_SEED_DIR and checks both directions.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_TOOL = os.path.join(_REPO, "tools", "dtt-capture.py")
_SKILL = os.path.join(_REPO, ".claude", "skills", "dtt-capture", "SKILL.md")
sys.path.insert(0, os.path.join(_REPO, "tools"))
import roadmap_seed_lib as lib  # noqa: E402


def _run(args, seed_dir):
    env = dict(os.environ, NOS_SEED_DIR=str(seed_dir))
    return subprocess.run([sys.executable, _TOOL, *args], env=env,
                          capture_output=True, text=True)


def test_valid_capture_writes_a_parseable_row(tmp_path):
    r = _run(["--slug", "an-idea", "--title", "A captured idea", "--track", "platform",
              "--task-type", "design", "--status", "next", "--body", "the prose"], tmp_path)
    assert r.returncode == 0, r.stderr
    f = tmp_path / "an-idea.md"
    assert f.is_file()
    row = lib.parse_file(str(f))          # the loader's own parser accepts it
    assert row["slug"] == "an-idea" and row["title"] == "A captured idea"
    assert row.get("status") == "next"


def test_bad_slug_is_refused(tmp_path):
    r = _run(["--slug", "bad slug", "--title", "x", "--track", "platform"], tmp_path)
    assert r.returncode != 0 and "row id" in r.stderr
    assert not (tmp_path / "bad slug.md").exists()


def test_unknown_task_type_is_refused(tmp_path):
    r = _run(["--slug", "ok", "--title", "x", "--track", "platform",
              "--task-type", "not-a-type", "--body", "b"], tmp_path)
    assert r.returncode != 0 and "task_type" in r.stderr


def test_unknown_status_is_refused(tmp_path):
    # This is the new home of the "only a declared status is written" invariant
    # (it left test_the_roadmap_declares when statuses moved to the private repo).
    r = _run(["--slug", "ok", "--title", "x", "--track", "platform",
              "--status", "not-a-status", "--body", "b"], tmp_path)
    assert r.returncode != 0 and "status" in r.stderr


def test_existing_needs_update_flag(tmp_path):
    a = ["--slug", "dup", "--title", "first", "--track", "platform", "--body", "b"]
    assert _run(a, tmp_path).returncode == 0
    # second write without --update must refuse
    assert _run(a, tmp_path).returncode != 0
    # with --update it overwrites
    assert _run(a + ["--update", "--title", "second"], tmp_path).returncode == 0
    assert lib.parse_file(str(tmp_path / "dup.md"))["title"] == "second"


def test_skill_exists_and_delegates_to_the_tool():
    assert os.path.isfile(_SKILL), "the dtt-capture skill is missing"
    txt = open(_SKILL, encoding="utf-8").read()
    assert "tools/dtt-capture.py" in txt, "the skill must route writes through the tool"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
