"""Docker CLI symlinks get a destination directory before they are linked.

``tasks/iiab/docker-prereqs.yml`` links the CLI out of Docker.app into
``/usr/local/bin``. A fresh Apple Silicon Mac has no ``/usr/local/bin``
(Homebrew lives in ``/opt/homebrew``), so every link failed with a
misleading ``No such file or directory`` and stopped the first install
(thisisait/nOS#40).

Each ``state: link`` task must be preceded by a task that ensures the
directory its links land in.
"""

from __future__ import annotations

import pathlib
import posixpath

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TASKS = REPO / "tasks/iiab/docker-prereqs.yml"


def _file_args(task):
    return task.get("ansible.builtin.file") or task.get("file") or {}


def test_link_tasks_have_their_directory_ensured_first():
    tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8")) or []
    ensured: set[str] = set()
    links = 0
    for task in tasks:
        args = _file_args(task)
        if args.get("state") == "directory":
            ensured.add(str(args.get("path", "")).rstrip("/"))
        if args.get("state") == "link":
            links += 1
            dest_dir = posixpath.dirname(str(args.get("dest", "")))
            assert dest_dir in ensured, (
                f"{task.get('name')!r} links into {dest_dir} without a prior "
                "`state: directory` task for it (fresh Apple Silicon has none)"
            )
    assert links, "gate went blind: no `state: link` task found"
