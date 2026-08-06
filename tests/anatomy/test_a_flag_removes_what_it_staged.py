"""A conditional copy is half a switch.

THE SHAPE. `ansible.builtin.copy` under a `when:` decides whether to WRITE a
file. Nothing in that task decides to delete it. So the flag is a one-way
door: turning it on stages the file, turning it off leaves the last copy
exactly where it was, running.

WHERE IT BIT, 2026-08-06. `roles/pazny.wordpress/tasks/main.yml` staged three
mu-plugins behind flags and removed none of them. WordPress auto-loads
everything in `mu-plugins/` — there is no activation step and no admin list to
notice it in. So flipping `wordpress_cve_63030_mitigate` to false, which is
what the pin-bump recipe in `default.config.yml` instructed, would have left
`/wp-json/batch/v1/` unregistered forever; and the same recipe's next
instruction — delete the PHP file — would have removed the only explanation of
why the batch REST API was dead. Measured that day: the mu-plugin was live
inside `iiab-wordpress-1` while the 6.9.4 core that justified it was being
replaced by a patched 7.0.2.

It is the flag/effect split this repo keeps meeting: **the flag records an
intention and something else has to carry it out.** Same family as
`dispatched_at` stamped by the sender, `status=scanned` written by a scan that
never ran, and the halt that three documents announced and no code performed.

THE RULE. For a directory the estate auto-loads, every conditionally staged
file needs the other half — a task that removes it when the condition is false.
This gate holds that for `mu-plugins/`, the one auto-load surface in the repo
today. It is deliberately scoped: a conditional copy into a directory that
requires explicit activation is not the same hazard.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORDPRESS_TASKS = REPO / "roles/pazny.wordpress/tasks/main.yml"

#: The auto-load surface. A file landing here runs on the next request with no
#: further step, which is what makes an un-removed copy invisible.
AUTOLOAD_DIR = "mu-plugins/"


def _tasks(path: Path) -> list[dict]:
    docs = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [t for t in docs if isinstance(t, dict)]


def _staged_conditionally(tasks: list[dict]) -> dict[str, str]:
    """{filename: the `when` that gates it} for conditional copies into the
    auto-load directory."""
    out: dict[str, str] = {}
    for task in tasks:
        copy = task.get("ansible.builtin.copy") or task.get("copy")
        if not isinstance(copy, dict):
            continue
        dest = str(copy.get("dest", ""))
        if AUTOLOAD_DIR not in dest:
            continue
        when = task.get("when")
        if when is None:
            continue  # unconditional: always present, nothing to undo
        out[dest.rsplit("/", 1)[-1]] = str(when)
    return out


def _removed(tasks: list[dict]) -> set[str]:
    """Filenames some task can delete from the auto-load directory."""
    removed: set[str] = set()
    for task in tasks:
        file_mod = task.get("ansible.builtin.file") or task.get("file")
        if not isinstance(file_mod, dict) or file_mod.get("state") != "absent":
            continue
        path = str(file_mod.get("path", ""))
        if AUTOLOAD_DIR not in path:
            continue
        # Either a literal filename, or a loop whose items name them.
        literal = path.rsplit("/", 1)[-1]
        if "{{" not in literal:
            removed.add(literal)
            continue
        for item in task.get("loop") or []:
            if isinstance(item, dict):
                for value in item.values():
                    if isinstance(value, str) and value.endswith(".php"):
                        removed.add(value)
            elif isinstance(item, str) and item.endswith(".php"):
                removed.add(item)
    return removed


def test_every_conditionally_staged_mu_plugin_can_be_removed():
    tasks = _tasks(WORDPRESS_TASKS)
    staged = _staged_conditionally(tasks)
    assert staged, (
        "no conditionally staged mu-plugin found — either the role changed "
        "shape or this gate has gone blind and is passing on an empty set"
    )

    removed = _removed(tasks)
    orphans = sorted(set(staged) - removed)
    assert not orphans, (
        "these mu-plugins are staged behind a flag and nothing removes them "
        "when it goes false. WordPress auto-loads mu-plugins/, so the last "
        "copy keeps running with no activation step and no UI to notice it "
        "in:\n  " + "\n  ".join(f"{f}  (staged when: {staged[f]})" for f in orphans)
    )


def test_the_removal_fires_on_the_negation_of_the_staging_condition():
    """Removal gated by the SAME condition as staging would delete the file it
    just wrote. The negation is the whole point, so it is asserted rather than
    assumed from the task's name."""
    tasks = _tasks(WORDPRESS_TASKS)
    removers = [
        t for t in tasks
        if isinstance(t.get("ansible.builtin.file"), dict)
        and t["ansible.builtin.file"].get("state") == "absent"
        and AUTOLOAD_DIR in str(t["ansible.builtin.file"].get("path", ""))
    ]
    assert removers, "no removal task for the auto-load directory"
    for task in removers:
        when = str(task.get("when", ""))
        assert re.search(r"\bnot\b", when), (
            f"the mu-plugin removal task's condition is {when!r} — without a "
            f"negation it deletes what the staging task just wrote"
        )


def test_the_mitigation_file_survives_its_own_flag():
    """The pin-bump recipe said to DELETE the CVE mu-plugin once the flag went
    false. Keeping it is deliberate: a rollback to the vulnerable core is
    exactly when the mitigation is wanted again, and `when: true` against a
    missing `src:` fails the play rather than protecting anything."""
    php = REPO / "roles/pazny.wordpress/files/cve-2026-63030-batch-block.php"
    assert php.is_file(), (
        "cve-2026-63030-batch-block.php was deleted. wordpress_cve_63030_"
        "mitigate can still be set to true, and the copy task would then fail "
        "on a missing source — a flag that cannot be turned back on."
    )
