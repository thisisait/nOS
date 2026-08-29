"""A provisioned dashboard's SQL must run, and the file must be provisioned.

TWO FAILURES, ONE FILE, and neither is hypothetical.

THE SQL. Grafana renders a broken query as an empty panel. An empty panel and a
panel over an empty table look the same, so a typo in a `rawQueryText` is a
dashboard that reports "nothing is wrong" for as long as nobody re-reads it —
this estate's signature defect, on the surface the operator glances at rather
than in code anyone reviews. Every `wing_sqlite` query here is executed against
an EMPTY database built from the committed schema artifact: that proves the SQL
parses and the columns exist, which is what a typo breaks. It cannot prove the
numbers mean anything, and does not claim to.

THE REGISTRATION. `plugin.yml` lists dashboards by name, so a file added to
`provisioning/dashboards/` and not to that list is never copied to the estate.
It renders in review, passes every other check, and does not exist on the host.

WHAT THIS GATE WOULD NOT HAVE CAUGHT, said plainly because it is the more
interesting defect: `22-ai-agents.json`'s success-rate panel ran perfectly and
counted `status = 'idle'` — "the process ended" — as success. 18 of 55 sessions
ended with no outcome at all, so the panel read 72.7% where the honest figure is
20.0%. Valid SQL, correct column, wrong question. No gate reads questions.
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import re
import sqlite3
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGIN = REPO / "files/anatomy/plugins/grafana-base/plugin.yml"
DASH_DIR = REPO / "files/anatomy/plugins/grafana-base/provisioning/dashboards"
SCHEMA = REPO / "files/anatomy/skills/contracts/wing.db-schema.sql"
WING_UID = "wing_sqlite"


def _listed() -> set[str]:
    """The `files:` block under `provisioning.dashboards`, read as text.

    Parsed with a regex rather than yaml on purpose: the block is inside a
    Jinja-templated manifest that `yaml.safe_load` handles today and might not
    tomorrow, and this only needs the filenames.
    """
    body = PLUGIN.read_text(encoding="utf-8")
    block = body[body.index("  dashboards:"):]
    return set(re.findall(r"^\s+- (\d\d-[\w-]+\.json)$", block, re.M))


def _dashboards() -> list[pathlib.Path]:
    return sorted(DASH_DIR.glob("*.json"))


def _empty_wing_db() -> sqlite3.Connection:
    """Every CREATE TABLE the estate puts in wing.db, and no rows.

    TWO WRITERS, ONE FILE. Wing owns most of the schema (the committed
    contract artifact); Bone owns the `loop_*` tables and creates them in the
    same database. A dashboard joining `loop_proposals` to `agent_sessions`
    crosses that line, which is exactly why the loop is worth a dashboard — so
    the fixture has to cross it too. Bone keeps its DDL and its later columns
    as importable data, in its own words "so the gate can read it".

    Rows would make this a test of the estate's data; the question here is only
    whether the query can be prepared at all.
    """
    conn = sqlite3.connect(":memory:")
    for stmt in re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?.*?\n\);",
                           SCHEMA.read_text(encoding="utf-8"), re.S):
        conn.executescript(stmt)

    sys.path.insert(0, str(REPO / "files/anatomy/bone"))
    import ledger  # noqa: PLC0415 — imported for its DDL, not its behaviour

    conn.executescript(ledger._DDL)
    for table, column, decl in ledger._ADDED_COLUMNS:
        with contextlib.suppress(sqlite3.OperationalError):   # already present
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    return conn


def test_every_dashboard_file_is_provisioned() -> None:
    on_disk = {p.name for p in _dashboards()}
    missing = sorted(on_disk - _listed())
    assert not missing, (
        f"{missing} sit in provisioning/dashboards/ and are not in plugin.yml's "
        "`files:` list, so the loader never copies them — they exist in review "
        "and not on the host."
    )


def test_the_list_names_nothing_that_is_gone() -> None:
    stale = sorted(_listed() - {p.name for p in _dashboards()})
    assert not stale, f"plugin.yml lists {stale}, which no longer exist"


@pytest.mark.parametrize("path", _dashboards(), ids=lambda p: p.name)
def test_every_wing_sqlite_query_parses(path: pathlib.Path) -> None:
    dash = json.loads(path.read_text(encoding="utf-8"))
    conn = _empty_wing_db()
    checked = 0
    for panel in dash.get("panels", []):
        ds = panel.get("datasource") or {}
        if ds.get("uid") != WING_UID:
            continue
        for target in panel.get("targets") or []:
            query = target.get("rawQueryText") or target.get("queryText")
            if not query:
                continue
            checked += 1
            try:
                conn.execute(query).fetchall()
            except sqlite3.Error as exc:
                raise AssertionError(
                    f"{path.name} · panel {panel.get('title')!r}: {exc}\n"
                    f"  {query}\n"
                    "Grafana renders this as an empty panel, which is "
                    "indistinguishable from a panel over an empty table."
                ) from None
    if path.name == "25-loop.json":
        assert checked >= 8, (
            f"only {checked} wing_sqlite queries in the loop dashboard — panels "
            "were removed, or their datasource moved and they now query nothing")


def test_the_two_targets_of_a_panel_do_not_disagree() -> None:
    """Grafana's sqlite plugin carries the query twice (`rawQueryText` is what
    the editor shows, `queryText` is what runs). Editing one is a panel that
    reads differently from how it behaves — and the editor is the half a human
    checks."""
    for path in _dashboards():
        for panel in json.loads(path.read_text(encoding="utf-8")).get("panels", []):
            for target in panel.get("targets") or []:
                raw, run = target.get("rawQueryText"), target.get("queryText")
                if raw is None or run is None:
                    continue
                assert raw == run, (
                    f"{path.name} · {panel.get('title')!r}: rawQueryText and "
                    "queryText differ, so the panel shows one query and runs "
                    "another")
