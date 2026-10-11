"""The thalamus ledger speaks AgentKit's columns and event types, by name.

WHY. A function moved from AgentKit into the thalamus is compared row by row
against Wing's ledger. That only works if every thalamus column exists in
Wing's table under the same name and type, every Wing NOT NULL column without
a default is filled, and every event type is one the contract lists. The
oracle is Wing's SQL file and files/anatomy/contracts/event-types.yml, never a
list copied into this test. The Rust writer is run too: `cargo test ledger`.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CRATE = REPO / "files/anatomy/thalamus/thalamus"
LEDGER = CRATE / "src/ledger.rs"
WING_SQL = REPO / "files/anatomy/wing/db/schema-extensions.sql"
EVENT_TYPES = REPO / "files/anatomy/contracts/event-types.yml"
#: thalamus table -> the Wing table it is a subset of
MIRROR = {"sessions": "agent_sessions", "events": "events"}
CONSTRAINT = re.compile(r"^(PRIMARY|UNIQUE|FOREIGN|CHECK|CONSTRAINT)\b")
TYPE_ARM = re.compile(r'=>\s*"([a-z][a-z0-9_.]*)"')


def _tables(sql: str) -> dict[str, dict[str, str]]:
    """{table: {column: declaration}} from every CREATE TABLE in the text."""
    sql = re.sub(r"--[^\n]*", "", sql)
    out: dict[str, dict[str, str]] = {}
    for name, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\s*\);", sql, re.S):
        cols = {}
        for line in body.split("\n"):
            line = line.strip().rstrip(",")
            if line and not CONSTRAINT.match(line):
                col, decl = line.split(None, 1)
                cols[col] = decl
        out[name] = cols
    return out


def _strays(rust: str, wing: str) -> list[str]:
    ours, theirs, bad = _tables(rust), _tables(wing), []
    if set(ours) != set(MIRROR):
        bad.append(f"ledger tables {sorted(ours)} != {sorted(MIRROR)}")
    for t, cols in ours.items():
        w = theirs.get(MIRROR.get(t, ""), {})
        for col, decl in cols.items():
            if col not in w:
                bad.append(f"{t}.{col}: not a column of Wing {MIRROR.get(t)}")
            elif decl.split()[0] != w[col].split()[0]:
                bad.append(f"{t}.{col}: {decl.split()[0]} here, {w[col].split()[0]} in Wing")
        for col, decl in w.items():
            if "NOT NULL" in decl and "DEFAULT" not in decl and col not in cols:
                bad.append(f"{t}: misses Wing's required {MIRROR[t]}.{col}")
    return bad


def _unlisted(rust: str) -> tuple[set[str], set[str]]:
    used = set(TYPE_ARM.findall(rust))
    return used, used - set(yaml.safe_load(EVENT_TYPES.read_text(encoding="utf-8"))["types"])


def _rust() -> str:
    return LEDGER.read_text(encoding="utf-8")


def test_every_ledger_column_is_a_wing_column():
    assert not _strays(_rust(), WING_SQL.read_text(encoding="utf-8"))


def test_a_planted_column_goes_red():
    planted = _rust().replace("CREATE TABLE IF NOT EXISTS sessions (",
                              "CREATE TABLE IF NOT EXISTS sessions (\n    planted_col TEXT,", 1)
    assert "sessions.planted_col: not a column of Wing agent_sessions" in _strays(
        planted, WING_SQL.read_text(encoding="utf-8"))


def test_every_event_type_is_in_the_contract():
    used, unlisted = _unlisted(_rust())
    assert len(used) >= 7, f"the type extractor matched only {sorted(used)}"
    assert not unlisted


def test_a_planted_type_goes_red():
    _, unlisted = _unlisted(_rust().replace('=> "agent_message"', '=> "agent_chatter"', 1))
    assert unlisted == {"agent_chatter"}


@pytest.mark.skipif(not shutil.which("cargo"), reason="cargo runs the ledger writer")
def test_the_writer_runs():
    r = subprocess.run(["cargo", "test", "--quiet", "--manifest-path", str(CRATE / "Cargo.toml"), "ledger"],
                       capture_output=True, text=True, timeout=600, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert re.search(r"[1-9]\d* passed", r.stdout), r.stdout
