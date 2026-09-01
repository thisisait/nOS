"""`backup.sh` must keep `set -o pipefail`, because every `rc=$?` depends on it.

The script backs up by streaming: `mariadb-dump | gzip | encrypt_stream |
aws s3 cp`, then reads `rc=$?`. Without `pipefail` that reads the exit status
of `aws s3 cp` — the LAST command — so a dump that failed with access denied
would still gzip nothing, upload it, and be logged `OK`. Measured on this
host with the exact shape:

    set -u -o pipefail;  false | gzip -c | cat  -> rc=1
    set -u             ;  false | gzip -c | cat -> rc=0

`set -u -o pipefail` on line 8 is what makes every `rc=$?` in the file mean
what it says, for the mariadb, postgresql, volume, authentik and keap steps
alike. Nothing else re-checks any of them.

WHY THIS GATE, AND NOT A FIX. On 2026-09-01 a review reported the missing-
pipefail bug as live and I relayed it before checking. It is not live — the
line is there. But the belief is not baseless: the sibling gate
`test_a_snapshot_is_opened_before_it_is_uploaded.py` asserted in its own
docstring that backup.sh lacked pipefail — written when that was true, never
updated when the line landed. So the estate simultaneously
depends on that line and documents its absence, and deleting it would look
supported by the test suite. That is what this pins.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKUP = ROOT / "roles/pazny.backup/files/backup.sh"


def test_pipefail_is_set_before_any_pipeline_rc() -> None:
    body = BACKUP.read_text(encoding="utf-8")
    m = re.search(r"^set\s+.*-o\s+pipefail", body, re.M)
    assert m, (
        "backup.sh no longer sets `-o pipefail`. Every `rc=$?` in this file "
        "follows a pipeline ending in `aws s3 cp`, so without it a failed "
        "dump uploads an empty artifact and is logged OK — silently, nightly.")

    first_rc = body.index("rc=$?") if "rc=$?" in body else len(body)
    assert m.start() < first_rc, (
        "`pipefail` is set AFTER the first `rc=$?`, so the reads above it are "
        "still the last command's status")


def test_the_shell_actually_behaves_that_way() -> None:
    """Assert the behaviour, not the string — the string is only a proxy for it."""
    with_pf = subprocess.run(
        ["bash", "-c", "set -u -o pipefail; false | gzip -c | cat >/dev/null; echo $?"],
        capture_output=True, text=True, timeout=30).stdout.strip()
    without = subprocess.run(
        ["bash", "-c", "set -u; false | gzip -c | cat >/dev/null; echo $?"],
        capture_output=True, text=True, timeout=30).stdout.strip()
    assert with_pf == "1", f"pipefail did not propagate the failure: rc={with_pf!r}"
    assert without == "0", (
        f"a failing head-of-pipe reported rc={without!r} WITHOUT pipefail — if this "
        "ever becomes non-zero the gate above is guarding something that no "
        "longer matters, and should be re-read rather than trusted")


def test_the_sibling_gate_does_not_still_deny_it() -> None:
    """A gate that documents the opposite makes deleting the line look safe."""
    sibling = ROOT / "tests/anatomy/test_a_snapshot_is_opened_before_it_is_uploaded.py"
    if not sibling.is_file():
        return
    text = sibling.read_text(encoding="utf-8")
    # Substring over prose, which is the shape this repo distrusts — and it
    # bit immediately: the first correction QUOTED the false sentence in order
    # to disown it, and this tripped on the quote. The phrase is now absent
    # rather than explained, and git history holds the original wording.
    assert "does not `set -o pipefail`" not in text, (
        "test_a_snapshot_is_opened_before_it_is_uploaded.py still states that "
        "backup.sh does not set pipefail. It does, on line 8, and the whole "
        "file's error handling rests on it. A stale claim inside a gate is the "
        "one place a reader will not think to check.")
