"""Anatomy CI gate — blank-reset must wipe ALL OpenTofu Authentik state.

When blank=true runs with the tofu engine, tasks/blank-reset.yml resets the
OpenTofu Authentik working state so the next `tofu apply` CREATEs cleanly against
the wiped tenant (stale pks across blanks → 400 collisions otherwise).

The original reset removed only `terraform.tfstate` + `terraform.tfstate.backup`
(singular). But OpenTofu writes a *timestamped* `terraform.tfstate.<epoch>.backup`
on every apply — dozens of these pile up in the repo working tree (gitignored,
but they muddy which state is live and clutter `git status` / file listings).
The blank's wipe-all contract has to remove those too.

This gate pins:
  1. The singular-backup removal task still exists (no regression).
  2. A find task discovers the timestamped backups via the glob
     `terraform.tfstate.*.backup`.
  3. A removal task deletes the discovered backups (state: absent).
  4. Both new tasks are gated behind the same tofu-engine `when:` as the
     original reset (don't touch a blueprint-engine tree).
  5. .gitignore already covers the timestamped backups (so step (2) of the
     proposed fix is a no-op, verified — not silently assumed).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
BLANK_RESET_PATH = REPO_ROOT / "tasks" / "blank-reset.yml"
GITIGNORE_PATH = REPO_ROOT / ".gitignore"

BACKUP_GLOB = "terraform.tfstate.*.backup"
TOFU_WHEN_FRAGMENT = "authentik_engine"


def _load_tasks() -> list[dict]:
    data = yaml.safe_load(BLANK_RESET_PATH.read_text())
    assert isinstance(data, list), "blank-reset.yml must be a task list"
    return data


def _task_name(task: dict) -> str:
    return str(task.get("name", ""))


def test_singular_state_reset_still_present():
    """No regression: the original singular-backup reset must survive."""
    tasks = _load_tasks()
    reset = [
        t for t in tasks
        if "Reset OpenTofu Authentik state" in _task_name(t)
    ]
    assert reset, "singular tofu state-reset task disappeared from blank-reset.yml"
    loop = reset[0].get("loop", [])
    assert "terraform.tfstate" in loop, "terraform.tfstate no longer wiped"
    assert "terraform.tfstate.backup" in loop, "singular .backup no longer wiped"


def test_find_task_discovers_timestamped_backups():
    """A find task must enumerate the timestamped backups by glob."""
    tasks = _load_tasks()
    find_tasks = [t for t in tasks if "ansible.builtin.find" in t]
    matching = [
        t for t in find_tasks
        if str(t["ansible.builtin.find"].get("patterns", "")) == BACKUP_GLOB
        and "terraform/authentik" in str(t["ansible.builtin.find"].get("paths", ""))
    ]
    assert matching, (
        "no find task globs 'terraform.tfstate.*.backup' under "
        "terraform/authentik — timestamped backups would survive a blank"
    )
    # The find must register a result for the removal loop to consume.
    assert matching[0].get("register"), "find task does not register a result var"


def test_removal_task_deletes_discovered_backups():
    """A file:absent loop must consume the find register and delete backups."""
    tasks = _load_tasks()

    # Locate the find task's register name.
    find_register = None
    for t in tasks:
        f = t.get("ansible.builtin.find")
        if f and str(f.get("patterns", "")) == BACKUP_GLOB:
            find_register = t.get("register")
            break
    assert find_register, "could not locate the tofu-backup find register"

    removal = []
    for t in tasks:
        fmod = t.get("ansible.builtin.file")
        loop = t.get("loop", "")
        if (
            fmod
            and fmod.get("state") == "absent"
            and find_register in str(loop)
        ):
            removal.append(t)
    assert removal, (
        f"no file:absent task loops over {find_register}.files — "
        "the discovered timestamped backups are never removed"
    )


def test_new_tasks_share_the_tofu_engine_gate():
    """The find + removal tasks must be gated behind the same tofu `when:`."""
    tasks = _load_tasks()
    for t in tasks:
        f = t.get("ansible.builtin.find")
        fmod = t.get("ansible.builtin.file")
        loop = str(t.get("loop", ""))
        is_backup_find = (
            f and str(f.get("patterns", "")) == BACKUP_GLOB
        )
        is_backup_removal = (
            fmod
            and fmod.get("state") == "absent"
            and "_blank_tofu_backups" in loop
        )
        if is_backup_find or is_backup_removal:
            when = str(t.get("when", ""))
            assert TOFU_WHEN_FRAGMENT in when, (
                f"task {_task_name(t)!r} is not gated behind the tofu engine "
                f"`when:` — it would touch a blueprint-engine tree"
            )


def test_gitignore_covers_timestamped_backups():
    """Proposed-fix step (2) is already satisfied — verify, don't duplicate.

    `terraform/**/terraform.tfstate.*` must be present so the timestamped
    backups never leak into git. If this fails, the .gitignore rule regressed
    and a literal `terraform.tfstate.*.backup` rule must be added.
    """
    lines = {
        ln.strip()
        for ln in GITIGNORE_PATH.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }
    covered = any(
        re.fullmatch(r"terraform/\*\*/terraform\.tfstate\.\*", ln)
        or ln == "terraform.tfstate.*.backup"
        or re.fullmatch(r"terraform/\*\*/terraform\.tfstate\.\*\.backup", ln)
        for ln in lines
    )
    assert covered, (
        ".gitignore no longer covers timestamped tofu backups — add "
        "'terraform/**/terraform.tfstate.*' (or 'terraform.tfstate.*.backup')"
    )
