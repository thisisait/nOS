"""Gate: a confirmed removal stops when the pre-wipe backup did not complete.

Operator 2026-10-02 ("we must have working backups"), reversing the 07-25
warn-only choice: with -y there is no interactive pause, so a failed snapshot
used to let remove=all delete data that existed nowhere else.
"""
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = yaml.safe_load((REPO / "tasks/pre-wipe-backup.yml").read_text())
VERDICT = TASKS[-1]
OK = {"_prewipe_backup_sh": {"stat": {"exists": True}}, "_prewipe_copy1": {"rc": 0},
      "_prewipe_restic": {"rc": 0}, "_prewipe_snapshot": {"rc": 0}, "restic_repo": "/r"}


def _passes(ctx) -> bool:
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)  # as Ansible chains
    env.filters["bool"] = lambda v: str(v).lower() in ("1", "true", "yes", "y", "on")
    return all(env.from_string("{{ (" + c + ") }}").render(**ctx) == "True"
               for c in VERDICT["ansible.builtin.assert"]["that"])


def test_the_verdict_is_last_and_on_by_default():
    assert "ansible.builtin.assert" in VERDICT, "the verdict must be the last pre-wipe step"
    assert VERDICT["when"] == "prewipe_snapshot_required | default(true) | bool"


def test_a_complete_backup_passes_and_each_missing_piece_stops():
    assert _passes(OK)
    for key, bad in (("_prewipe_snapshot", {"rc": 1}), ("_prewipe_copy1", {"rc": 2}),
                     ("_prewipe_restic", {"rc": 127}), ("_prewipe_backup_sh", {"stat": {"exists": False}})):
        assert not _passes({**OK, key: bad}), key
    assert not _passes({k: v for k, v in OK.items() if k != "_prewipe_snapshot"}), "a skipped snapshot is not a snapshot"
    assert not _passes({**OK, "restic_repo": ""}), "no repo, no survivor (review 2026-10-04)"
