"""Anything installing into `~/.local/bin` must chown the tree back first.

`~/.local` is routinely left ROOT-owned — by an earlier `become` step, by a
`sudo pip install`, or baked that way into a CI runner image. An
operator-context `mkdir ~/.local/bin` then fails with EACCES on a directory
inside the user's own HOME, which reads as impossible and stops a run dead.

`roles/pazny.wing/tasks/main.yml` learned this and creates both `~/.local` and
`~/.local/bin` with `become: true` + `owner: <the operator>`, handing the tree
back so every later write needs no root. `tasks/nos-cli.yml` cited that
precedent in a comment and copied only the path from it — the Linux integration
job failed on exactly the predicted error (2026-07-22).

The rule: cite a precedent by MECHANISM, not by path. This gate makes the
mechanism mandatory for every file that installs there, so the next one cannot
inherit the comment without the fix.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]

# Files that install an executable into ~/.local/bin on Linux.
INSTALLERS = [
    pathlib.Path("tasks/nos-cli.yml"),
    pathlib.Path("roles/pazny.wing/tasks/main.yml"),
]


def _tasks(path: pathlib.Path):
    out = []

    def walk(items):
        for t in items or []:
            if not isinstance(t, dict):
                continue
            out.append(t)
            for key in ("block", "rescue", "always"):
                if key in t:
                    walk(t[key])

    walk(yaml.safe_load((REPO / path).read_text()))
    return out


def _file_module(task):
    return task.get("file") or task.get("ansible.builtin.file")


def test_every_local_bin_installer_chowns_the_tree():
    for rel in INSTALLERS:
        assert (REPO / rel).is_file(), f"{rel} is gone — move this gate with it"
        src = (REPO / rel).read_text()
        if "/.local/bin" not in src:
            continue  # no longer installs there; nothing to enforce

        chowners = []
        for t in _tasks(rel):
            mod = _file_module(t)
            if not mod:
                continue
            paths = str(mod.get("path", "")) + " " + str(t.get("loop", ""))
            if "/.local" not in paths:
                continue
            if t.get("become") and "owner" in mod:
                chowners.append(str(t.get("name", "")))

        assert chowners, (
            f"{rel} installs into ~/.local/bin but no task creates that tree "
            "with `become: true` + `owner:`. A root-owned ~/.local (earlier "
            "become step, sudo pip, or a CI runner image) then makes an "
            "operator-context mkdir fail with EACCES inside the user's own "
            "HOME. Mirror roles/pazny.wing/tasks/main.yml."
        )


def test_the_chown_covers_the_parent_not_only_bin():
    """Chowning only `~/.local/bin` cannot help — the mkdir fails on the parent."""
    for rel in INSTALLERS:
        src = (REPO / rel).read_text()
        if "/.local/bin" not in src:
            continue
        for t in _tasks(rel):
            mod = _file_module(t)
            if not mod or not t.get("become") or "owner" not in mod:
                continue
            covered = str(mod.get("path", "")) + " " + str(t.get("loop", ""))
            if "/.local" not in covered:
                continue
            assert "/.local'" in covered or "/.local\"" in covered or (
                "/.local" in covered and "/.local/bin" in covered
            ), (
                f"{rel} chowns ~/.local/bin without ~/.local itself; creating "
                "the child is what fails when the parent is root-owned"
            )
