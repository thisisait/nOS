"""Every wing.db writer script must set a SQLite busy timeout.

WAL mode (a persistent on-file property set by init-db/migrate) lets many
readers coexist with one writer, but two *concurrent writers* still serialize —
and without a per-connection busy timeout the loser fails INSTANTLY with
"database is locked" instead of waiting. Scout surfaced this live 2026-07-15:
`gdpr-breach:breach-deadline-scan` (escalate rc=3) + `wing:dispatch-
notifications` (dispatch-notifications.php) failed `database is locked` 4x/7d.

This gate pins the invariant so a new writer script can't regress it: any
bin/*.php that opens wing.db read-write (raw SQLite3 not READONLY, or PDO
sqlite) must call busyTimeout()/PRAGMA busy_timeout / PDO::ATTR_TIMEOUT.
"""
import re
import pathlib

BIN = pathlib.Path(__file__).resolve().parents[2] / "files/anatomy/wing/bin"


def _writers():
    for f in sorted(BIN.glob("*.php")):
        src = f.read_text()
        sqlite_rw = re.search(r"new SQLite3\((?![^)]*READONLY)", src)
        pdo_sqlite = re.search(r"new PDO\('sqlite:", src)
        if sqlite_rw or pdo_sqlite:
            yield f, src


def test_every_wing_db_writer_sets_busy_timeout():
    missing = []
    for f, src in _writers():
        if not ("busyTimeout" in src or "busy_timeout" in src or "ATTR_TIMEOUT" in src):
            missing.append(f.name)
    assert not missing, (
        "wing.db writer scripts with NO busy timeout (add "
        "$db->busyTimeout(5000) for SQLite3, or "
        "$db->setAttribute(PDO::ATTR_TIMEOUT, 5) for PDO — else they fail "
        f"'database is locked' instantly under concurrent writers): {missing}"
    )


def test_at_least_the_known_writers_are_covered():
    # Sanity: the enumeration actually finds the scout-flagged writers.
    names = {f.name for f, _ in _writers()}
    for expected in ("dispatch-notifications.php", "breach-scan.php"):
        assert expected in names, f"{expected} no longer detected as a wing.db writer"
