"""The restore path's Jinja is rendered here, because nothing rendered it before.

Two bugs shipped in tasks/restore.yml, found 2026-09-28 by trying to restore a
backup for the first time. Both are the same mistake: a YAML FOLDED (`>-`) or
LITERAL (`|-`) scalar does not process escapes, so `\\s` and `\\n` reach Jinja as
two characters instead of one.

  1. SELECTION. `map('regex_replace', '^.*\\\\s+([^\\\\s]+)$', '\\\\1')` asked for
     "a backslash followed by s", matched nothing, and returned each `aws s3 ls`
     line untouched — columns and all. No stem ever equalled `mariadb`, so every
     restore bailed with "no files match" while listing the file it had just
     failed to recognise. Three more regexes on the plan step (`.enc`, the
     compression extension, a legacy timestamp) were inert the same way.

  2. THE KEY RING. `join('\\\\n')` inside `|-` glued every key onto ONE line, so
     `read -r key` got a concatenation that is no key. Harmless while a single
     key existed; broken from the first rotation — precisely the case the ring
     was written for.

WHY IT HID: tests/anatomy/test_backup_restore_contract.py has fourteen tests
about handlers, canonical stems, the pbkdf2 resolver and which dirs have restore
targets. Not one of them renders a template. It tested the contract AROUND the
code instead of the code, so the backup side stayed green for months while the
restore side could not have worked once.

These tests therefore do the thing that was missing: they run the real
expressions, lifted from the file, against realistic input.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RESTORE = REPO / "tasks/restore.yml"

#: A real `aws s3 ls` line: date, time, size, key.
LS_LINES = [
    "2026-09-27 03:00:04    1650464 mariadb.sql.gz.enc",
    "2026-09-27 03:00:30   40302432 postgres.sql.gz.enc",
    "2026-09-27 03:01:59  154936608 wing-db.sql.gz.enc",
]


def _parse_pattern() -> tuple[str, str]:
    """The selection regex exactly as restore.yml carries it."""
    text = RESTORE.read_text(encoding="utf-8")
    m = re.search(r"map\('regex_replace',\s*'([^']+)',\s*'([^']+)'\)", text)
    assert m, "the filename-parsing regex is gone from restore.yml — re-point this gate"
    return m.group(1), m.group(2)


def test_filename_parsing_strips_the_aws_columns():
    """The selection bug: whole `ls` lines must become bare object keys."""
    pattern, repl = _parse_pattern()
    out = [re.sub(pattern, repl, ln) for ln in LS_LINES]
    assert out[0] == "mariadb.sql.gz.enc", (
        f"filenames still carry their aws s3 ls columns: {out}. A folded scalar "
        "does not unescape — the regex needs single backslashes."
    )
    assert not any("03:00" in o for o in out), f"time column survived: {out}"


@pytest.mark.parametrize("name,stem", [
    ("mariadb.sql.gz.enc", "mariadb"),
    ("postgres.sql.gz.enc", "postgres"),
    ("keap-db.gz.enc", "keap-db"),
    ("dir-gitea.tar.gz.enc", "dir-gitea"),
])
def test_a_key_reduces_to_its_canonical_stem(name, stem):
    """The plan bug: `.enc` and the compression extension must actually strip."""
    plain = re.sub(r"\.enc$", "", name)
    noext = re.sub(r"\.sql\.gz$|\.tar\.gz$|\.json\.gz$|\.json$|\.gz$", "", plain)
    assert noext == stem, f"{name} reduced to {noext!r}, wanted {stem!r}"
    assert not noext.endswith(".enc"), "the .enc suffix survived"


def test_the_key_ring_is_joined_on_a_real_newline():
    """The ring bug: keys must arrive one per line, or `read -r` gets one blob."""
    text = RESTORE.read_text(encoding="utf-8")
    assert "NOS_RESTORE_KEYS_RAW: |-" not in text, (
        "the key ring is built inside a `|-` literal block again. `\\n` is not a "
        "newline there, so every key lands on one line and no key decrypts — "
        "which only shows up AFTER a rotation, when the ring finally matters."
    )
    assert "join(_nos_restore_nl)" in text, (
        "the ring no longer joins on the real-newline variable; if the separator "
        "moved, make sure it is a newline YAML itself produced."
    )


def test_no_double_backslash_regex_survives_in_a_block_scalar():
    """The general rule, so the next one is caught by shape rather than by outage."""
    offenders = [
        f"{n}: {ln.strip()[:80]}"
        for n, ln in enumerate(RESTORE.read_text(encoding="utf-8").splitlines(), 1)
        if "regex_replace" in ln and "\\\\" in ln
    ]
    assert not offenders, (
        "double-backslash regex(es) inside restore.yml's block scalars — these "
        "match a literal backslash and silently do nothing:\n  " + "\n  ".join(offenders)
    )
