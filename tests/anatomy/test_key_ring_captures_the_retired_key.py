"""A rotation cannot compute the outgoing key from the variable it replaces.

MEASURED FAILURE, 2026-08-03. P2 retired the derived archive key and shipped a
key ring so archives written under the old key stayed readable. Both halves
landed in one commit (`f3f8db4d`), and they cancelled:

    roles/pazny.backup/defaults/main.yml   backup_encryption_passphrase: ""
    main.yml                               keep it IF `'_pw_' in <that same var>`

The default no longer held the derived value, so the condition could never be
true. The ring stayed `[]` while the live bucket held 86 archives encrypted
under the retired key — and the comment above the task named the precondition
its sibling edit had just removed: *"the only moment the old value is still
computable"*.

Nothing caught it because the run was GREEN. A ring that is empty because the
capture never fired looks exactly like a ring that is empty because there was
nothing to retire.

THE RULE THIS PINS, which is not specific to backups:

    The outgoing value must come from a source the rotation does not touch.

Derivation from the prefix was the weakness P2 removed — and it is also what
makes the retired key recoverable forever, so the ring can be reconstructed at
any time. That asymmetry is the whole reason this is repairable.

What this gate CANNOT see: whether the ring is non-empty on a converged host.
That is runtime, and it is the honest limit — `backup-verify.sh` is the reader
that would notice, which is why clause 4 pins that it consults the ring at all.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: The suffix the archive key was derived with before P2 retired it. A constant
#: of every pre-2026-08-03 host's past: changing it here orphans real archives,
#: so it is pinned rather than referenced.
HISTORICAL_SUFFIX = "_pw_backup_encryption"

#: The variable being replaced. Reading it inside the capture is the defect.
ROTATED = "backup_encryption_passphrase"

RING = "backup_encryption_keys_previous"


def _capture_task(main: str | None = None) -> str:
    """The set_fact that seeds the ring, isolated from the rest of main.yml.

    Located by its EFFECT (it assigns the ring), never by its name. The first
    draft matched the task name and was a weaker gate for it: replaying the
    broken 2026-08-02 version made it fail with "renamed or removed" instead of
    naming the defect, and any rename would have read as the same thing.
    The `main` argument exists so that replay is a real test — see the retro
    case at the bottom of this file.
    """
    main = (REPO / "main.yml").read_text(encoding="utf-8") if main is None else main
    # Split on task boundaries in plain Python. A regex spanning task bodies
    # was tried twice and failed twice — first by crossing the boundary (`\s`
    # matches a newline, so it reported a NEIGHBOURING task's mention of the
    # rotated var as this task's defect), then, once anchored, by backtracking
    # catastrophically on a 1400-line file. Splitting is exact and linear.
    blocks = re.split(r"\n(?=    - name:)", main)
    hits = [b for b in blocks if re.search(rf"^\s+{RING}:", b, re.M)]
    assert hits, (
        f"no task in main.yml assigns `{RING}` any more. If the ring is gone, "
        f"every archive written under the retired derived key becomes unopenable "
        f"by the estate's own tooling — delete this gate deliberately, not by drift."
    )
    assert len(hits) == 1, (
        f"{len(hits)} tasks assign `{RING}` — with more than one writer, this "
        f"gate can clear the clean one while the other reintroduces the defect"
    )
    return hits[0]


def _reads_the_rotated_var(task: str) -> bool:
    """The one clause, factored out so the retro case exercises the SAME code."""
    return ROTATED in task


def test_the_gate_fails_on_the_version_that_shipped_broken():
    """Retro-test. A gate that never saw its own defect proves nothing.

    This is the task exactly as it stood on 2026-08-02, when the run was green
    and the ring was empty.
    """
    shipped_broken = """
    - name: "[Security] Preserve the outgoing backup key so old archives stay readable"
      ansible.builtin.set_fact:
        backup_encryption_keys_previous: >-
          {{ (backup_encryption_keys_previous | default([])
              + [backup_encryption_passphrase])
             | unique }}
      when:
        - (backup_encryption_passphrase | default('')) | length > 0
        - "'_pw_' in (backup_encryption_passphrase | default(''))"
      no_log: true
      tags: ['always']

    - name: "[Security] something else"
"""
    task = _capture_task(shipped_broken)
    assert _reads_the_rotated_var(task), (
        "the gate no longer detects the defect it was written for — the broken "
        "version now reads as clean, which means the live clause is vacuous"
    )


def test_the_capture_does_not_read_the_variable_it_replaces():
    """The exact defect: capturing X by reading X, after X was emptied."""
    task = _capture_task()
    assert not _reads_the_rotated_var(task), (
        f"the ring-seeding task reads `{ROTATED}` — the variable the rotation "
        f"REPLACES. Its default is \"\" (minted at runtime), so at the moment "
        f"this task runs it cannot hold the outgoing value. This is the "
        f"2026-08-03 defect verbatim. Seed from a source the rotation does not "
        f"touch: the prefix plus the historical suffix."
    )


def test_the_capture_reconstructs_the_retired_key():
    """...and it must reconstruct the RIGHT one, or the ring holds a stranger."""
    task = _capture_task()
    assert "global_password_prefix" in task, (
        "the ring is seeded from something other than the master prefix — the "
        "retired key was `{prefix}" + HISTORICAL_SUFFIX + "`, and only the "
        "prefix reconstructs it"
    )
    assert HISTORICAL_SUFFIX in task, (
        f"the historical suffix `{HISTORICAL_SUFFIX}` is gone from the seeding "
        f"task. Measured against the live bucket on 2026-08-03: archives from "
        f"2026-07-26..08-02 decrypt with `{{prefix}}{HISTORICAL_SUFFIX}` and "
        f"with nothing else."
    )


def test_the_current_key_is_not_derived_after_all_this():
    """The point of the exercise. The ring is the mitigation, not the goal."""
    defaults = (REPO / "roles/pazny.backup/defaults/main.yml").read_text(encoding="utf-8")
    m = re.search(rf"^{ROTATED}:\s*(.*)$", defaults, re.M)
    assert m, f"{ROTATED} vanished from the backup role defaults"
    value = m.group(1).strip()
    assert "global_password_prefix" not in value, (
        f"{ROTATED} derives from the master prefix again — P2 undone. The ring "
        f"below it exists precisely because it stopped."
    )


def test_the_reader_actually_consults_the_ring():
    """A ring nothing reads is a list, not a mitigation.

    Pinned separately from the writer because the two failed independently:
    the writer never fired, and had it fired, only this loop would have made
    the entry mean anything.
    """
    verify = (REPO / "roles/pazny.backup/files/backup-verify.sh").read_text(encoding="utf-8")
    assert re.search(rf"for\s+\w+\s+in\s+{RING}", verify), (
        f"backup-verify.sh no longer iterates `{RING}` — archives written "
        f"under a retired key would report as corrupt rather than as needing "
        f"an older key"
    )
