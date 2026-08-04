"""A major version bump must bring the post-start automation with it.

MEASURED 2026-08-04. On 2026-07-24 the upgrade engine applied REM-073 and moved
`uptime_kuma_version` from 1.23.13 to 2.2.1 to close CVE-2026-33130. The bump
itself was correct and is not in question.

What travelled with it: nothing. Uptime Kuma 2 added a step v1 never had — it
asks which DATABASE to use before it will create one, and until that is
answered it runs `setup-database.js` INSTEAD of the application. That server
answers 200 on every route and satisfies the container healthcheck. So for ten
days the estate held a monitoring service that monitored nothing while every
signal we own — `docker ps` healthy, HTTP 200, the STRICT stack-health probe,
and the remediation queue's own `resolved_detail` ("container healthy on 2.2.1,
http 200. Verified 2026-07-24") — read green.

That verification line is the shape this repo keeps finding: it checked the two
things that CANNOT distinguish success from the failure that actually occurred.

THE GATE. `UPTIME_KUMA_DB_TYPE` is what makes the question answerable from the
compose file (`setup-database.js:96` → `this.needSetup = false`). So: if the
effective pin is 2.x or later, the compose template must set it. Run this
against the tree as it stood on 2026-07-24 and it fails — the pin was already
2.2.1 and the env var did not exist for another eleven days.

WHY THE EFFECTIVE PIN IS READ FROM default.config.yml. The role default still
says "1" and is outranked; reading the role alone reports a version that has
not run here since July. That is the standing `version-pins-default-config-
shadow` trap, and this gate reads the half that wins.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "default.config.yml"
ROLE = REPO / "roles/pazny.uptime_kuma"
COMPOSE = ROLE / "templates/compose.yml.j2"

# The env var Kuma 2 reads to skip its database-setup step. Named once.
DB_TYPE_ENV = "UPTIME_KUMA_DB_TYPE"


def _effective_pin() -> str:
    """The version that actually runs: default.config.yml outranks role defaults."""
    text = CONFIG.read_text(encoding="utf-8")
    m = re.search(r'^uptime_kuma_version:\s*["\']?([^"\'#\s]+)', text, re.MULTILINE)
    assert m, "uptime_kuma_version is no longer declared in default.config.yml"
    return m.group(1)


def _major(version: str) -> int:
    head = version.split(".", 1)[0]
    assert head.isdigit(), f"cannot read a major version out of {version!r}"
    return int(head)


def test_a_two_dot_x_pin_answers_the_database_question_in_compose():
    """The defect itself, as the thing that must stay false."""
    pin = _effective_pin()
    if _major(pin) < 2:
        pytest.skip(f"pin {pin} predates the 2.x setup-database step")

    compose = COMPOSE.read_text(encoding="utf-8")
    assert DB_TYPE_ENV in compose, (
        f"uptime_kuma_version is pinned to {pin}, but the compose template never "
        f"sets {DB_TYPE_ENV}. Kuma 2 will serve its setup wizard instead of the "
        f"application — answering 200 on every route and reporting `healthy` to "
        f"Docker the entire time, which is how this went unnoticed for ten days. "
        f"Set it in roles/pazny.uptime_kuma/templates/compose.yml.j2."
    )


def test_the_declared_database_type_is_one_kuma_accepts():
    """A typo here fails exactly like the missing var, and just as quietly."""
    pin = _effective_pin()
    if _major(pin) < 2:
        pytest.skip(f"pin {pin} predates the 2.x setup-database step")

    compose = COMPOSE.read_text(encoding="utf-8")
    m = re.search(rf'{DB_TYPE_ENV}\s*:\s*["\']?([a-z-]+)', compose)
    assert m, f"{DB_TYPE_ENV} is mentioned but not assigned a value"
    # Kuma 2 accepts these; anything else leaves needSetup true in practice
    # because writeDBConfig stores a type no driver claims.
    assert m.group(1) in {"sqlite", "mariadb", "postgres", "embedded-mariadb"}, (
        f"{DB_TYPE_ENV}={m.group(1)!r} is not a database type Kuma 2 knows"
    )


def test_no_task_reads_the_kuma_database_with_an_unguarded_sqlite3():
    """The reader that minted its own subject.

    `sqlite3 <path> "SELECT …"` CREATES <path> when it is missing. The
    disableAuth probe did that and left a 0-byte kuma.db on the live estate —
    which is not inert, because Kuma 2's setup-database.js branches on whether
    kuma.db is FOUND.

    Guarded reads go through files/read-setting.sh, which is exercised for real
    by test_kuma_reader_creates_nothing.py rather than pattern-matched here.
    """
    offenders = []
    for task_file in sorted((ROLE / "tasks").glob("*.yml")):
        for lineno, line in enumerate(task_file.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "sqlite3" not in stripped or "kuma.db" not in stripped:
                continue
            # A write is allowed to create the file; a READ is not.
            if re.search(r"\bSELECT\b", stripped, re.IGNORECASE):
                offenders.append(f"{task_file.relative_to(REPO)}:{lineno}")

    assert not offenders, (
        "these tasks read kuma.db with a bare sqlite3 call, which CREATES the "
        "file when it is absent and leaves a zero-byte database behind:\n  "
        + "\n  ".join(offenders)
        + "\nUse files/read-setting.sh, which refuses to open a path that is "
        "not already a non-empty database."
    )
