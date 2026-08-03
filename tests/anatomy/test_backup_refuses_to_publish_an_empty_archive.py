"""A backup that captured nothing must not be published as a backup.

MEASURED, 2026-08-03, against the live bucket. Six of eight directory sources
had produced an archive containing exactly one entry — `./` — on every nightly
for the entire life of the bucket:

    dir-gitea  dir-gitlab  dir-gitlab-config  dir-vaultwarden  dir-nodered
    dir-authentik        → 1 entry   (empty)
    dir-n8n              → 11 entries
    nos-state            → 2 entries (secrets.yml, state.yml)

The discriminator is the path, not the service: everything under `nos_data_root`
(`/Volumes/SSD1TB`) is empty, everything under `$HOME` is fine. The host `tar`
cannot read the external volume, while the `-d` guard above it still passes
because the mount point itself is visible.

WHY IT SURVIVED SO LONG: the archive streams STRAIGHT to S3
(`tar | encrypt | aws s3 cp -`), so the object is published before tar's exit
code is known. A 10 KB artifact then lists in the bucket exactly like a backup
does, and the retention rotation counts it as one.

The author had already met this class one line earlier — an ABSENT directory is
recorded as FAILED, with a comment naming the danger ("...while A9 still
reported 'Backup OK - N sources'"). Absent was handled; EMPTY was not. Being one
case short is the normal way this fails, which is why the gate pins both.

Two defences, and the gate wants both, because they fail in different places:

    * pre-flight  — refuse before writing anything; there is no taking an S3
                    object back once the stream has gone
    * post-check  — a source can list entries and still tar to nothing, so the
                    archive's MEMBER count decides and the object is withdrawn

Related: `test_backup_reaches_the_brain.py` (a vanished source recording
nothing), `test_key_ring_captures_the_retired_key.py` (same day, same estate).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "roles/pazny.backup/files/backup.sh"


def _run_dirs() -> str:
    body = SCRIPT.read_text(encoding="utf-8")
    start = body.index("run_dirs() {")
    end = body.index("\n}\n", start)
    return body[start:end]


def test_the_source_is_checked_before_anything_is_uploaded():
    """Pre-flight. The only moment at which refusing is still possible."""
    fn = _run_dirs()
    upload_at = fn.index("aws ")
    guard = re.search(r"ls -A .*\| wc -l", fn)
    assert guard, (
        "run_dirs no longer counts entries in the source directory before "
        "tarring it. Six services backed up nothing for weeks because a "
        "readable-but-empty path tars cleanly and uploads cleanly."
    )
    assert guard.start() < upload_at, (
        "the emptiness check sits AFTER the upload — by then the empty object "
        "is already in the bucket and listing like a backup"
    )


def test_an_empty_archive_is_withdrawn_rather_than_reported():
    """Post-check, for the source that lists entries and still tars to nothing."""
    fn = _run_dirs()
    assert "EMPTY_ARCHIVE_MEMBERS" in fn, (
        "the member-count check is gone — a partial permission failure would "
        "upload a padding-only archive and report OK"
    )
    assert re.search(r"s3 rm .*\$\{key\}", fn), (
        "an archive found to be empty is no longer REMOVED from the bucket. "
        "Leaving it there is worse than the failure: it occupies the day's slot "
        "and the rotation will keep it as though it held something."
    )


def test_the_absent_case_it_was_one_step_short_of_stays_covered():
    """The neighbouring guard that got this right, pinned so it cannot regress."""
    fn = _run_dirs()
    assert re.search(r'if \[\[ ! -d "\$\{path\}" \]\]', fn), (
        "the absent-directory guard vanished — an unmounted SSD would drop "
        "sources out of the nightly set silently"
    )


def test_emptiness_is_counted_not_weighed():
    """The check this file nearly shipped instead, and why it was wrong.

    A byte floor was written first: withdraw anything at or under 10272, the
    size every one of the six empty archives measured. It was caught before it
    shipped. tar pads to a 10240-byte minimum, so an archive holding three
    small files weighs the same as one holding nothing — the floor would have
    DELETED real backups, which is worse than the defect it was closing.
    `nos-state`, a genuine two-file archive, measures 10272 exactly.
    """
    body = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"^EMPTY_ARCHIVE_MEMBERS=(\d+)", body, re.M)
    assert m, "EMPTY_ARCHIVE_MEMBERS is not declared beside the other constants"
    assert int(m.group(1)) == 1, (
        "`tar -C path .` emits `./` as its first member, so 1 is the exact "
        "boundary between 'captured nothing' and 'captured something'"
    )
    assert "EMPTY_ARCHIVE_CEILING" not in body, (
        "a byte-size floor is back. Size cannot distinguish an empty archive "
        "from a small one — see this test's docstring."
    )
    fn = _run_dirs()
    assert "tar -czvf" in fn, (
        "the member list is no longer produced (`-v` dropped), so the count "
        "the withdrawal decision rests on cannot be taken"
    )
