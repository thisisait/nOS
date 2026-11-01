"""A Paperclip host workspace with `follow:` sits at its branch's tip after a converge.

THE SYMPTOM (2026-11-01). The HnedWeb oponent reviewed against /workspaces/nos, a clone
made by hand on 10-24 and never moved; it flagged two fixes already on dev as missing.

THE CHECK. Runs the role task's real shell against throwaway repos: a clone behind its
origin moves to the tip; a clone with local changes is refused, not reset; a folder that
is no clone is refused. CEILING: local file:// origins, not the network.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
TASK = "[pazny.paperclip] A followed workspace sits at its branch's tip"


def _script(path: Path) -> str:
    tasks = yaml.safe_load((REPO / "roles/pazny.paperclip/tasks/main.yml").read_text())
    t = next(t for t in tasks if t.get("name") == TASK)
    env = jinja2.Environment()
    env.filters["quote"] = lambda s: "'" + str(s).replace("'", "'\\''") + "'"
    return env.from_string(t["ansible.builtin.shell"]).render(item={"name": "nos", "path": str(path), "follow": "dev"})


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                               "HOME": str(cwd)}).stdout.strip()


def _origin_and_clone(tmp: Path) -> tuple[Path, Path]:
    origin = tmp / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "dev")
    (origin / "f").write_text("1\n")
    _git(origin, "add", "f")
    _git(origin, "commit", "-qm", "one")
    clone = tmp / "clone"
    _git(tmp, "clone", "-q", "-b", "dev", str(origin), str(clone))
    (origin / "f").write_text("2\n")
    _git(origin, "commit", "-qam", "two")
    return origin, clone


def _run(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", _script(path)], capture_output=True, text=True, timeout=60)


def test_a_clone_behind_moves_to_the_tip(tmp_path):
    origin, clone = _origin_and_clone(tmp_path)
    out = _run(clone)
    assert out.returncode == 0, out.stderr
    assert "moved" in out.stdout and _git(clone, "rev-parse", "HEAD") == _git(origin, "rev-parse", "HEAD")
    assert "at " in _run(clone).stdout, "a second converge at the tip must report no change"


def test_local_changes_are_refused_not_reset(tmp_path):
    _, clone = _origin_and_clone(tmp_path)
    (clone / "f").write_text("mine\n")
    out = _run(clone)
    assert out.returncode != 0 and "local changes" in out.stderr
    assert (clone / "f").read_text() == "mine\n"


def test_a_folder_that_is_no_clone_is_refused(tmp_path):
    (tmp_path / "plain").mkdir()
    out = _run(tmp_path / "plain")
    assert out.returncode != 0 and "no git clone" in out.stderr
