"""A restore --check must list backups before it may refuse them.

MEASURED 2026-09-15, unit-level `ansible-playbook --check` of
`tasks/restore.yml` (main.yml cannot load here — a galaxy role is
absent; `--tags restore --skip-tags always,stacks,core` is the tagged
shape, the unit play is the same tasks):

    TASK [[Restore] List backup objects at s3://backups/2026-09-15/]
    skipping: [127.0.0.1]
    TASK [[Restore] Bail if no backups exist at the requested date]
    fatal: No backups found at s3://backups/2026-09-15/

`command` performs nothing under `--check`. The registered `restore_ls`
comes back empty; `(stdout | default('') | trim | length) == 0` turns
that absence into a verdict. Same mechanism as fee 36 / the wing probes:
a dry run inventing a failure a converge does not have.

`check_mode: false` on the listing is the fix — `aws s3 ls` is a read.

SCOPE is the one path that was reached. MariaDB / PostgreSQL refusals
in this file sit inside `not ansible_check_mode` blocks; they were not
taken. The other fee-36 rows were not edited on suspicion.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
RESTORE = REPO / "tasks/restore.yml"


def _tasks(node):
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item)
    elif isinstance(node, dict):
        if any(k in node for k in ("name", "block", "when", "register")):
            yield node
        for key in ("block", "rescue", "always"):
            if key in node:
                yield from _tasks(node[key])


def test_restore_list_opts_out_of_check_mode() -> None:
    """The measured invented failure: skip the list, refuse on empty stdout."""
    doc = yaml.safe_load(RESTORE.read_text(encoding="utf-8"))
    tasks = list(_tasks(doc))
    listing = next(t for t in tasks if t.get("register") == "restore_ls")
    assert listing.get("check_mode") is False, (
        "tasks/restore.yml lists backups with a check-blind command; "
        "--check skips it and the next fail: treats empty stdout as "
        "'no backups'. Add check_mode: false — aws s3 ls is a read."
    )
    bail = next(
        t for t in tasks
        if "Bail if no backups exist" in str(t.get("name", ""))
    )
    assert "restore_ls" in str(bail.get("when", "")), (
        "the no-backups refusal no longer reads restore_ls — re-scope this gate"
    )
