"""Build-time fixture rows must not head the surfaces that answer
"is the loop working" — and must not vanish from history either.

MEASURED 2026-08-19 (docs/idea/13-fable-review.md §4): 9 of 13 `loop_proposals` rows in the
operator's LIVE ledger carried `weakness_id` `w1`/`w2` — placeholder ids no
source in `weaknesses.py` SOURCE_ORDER can emit, written 2026-08-02 by
`agent:x` while the ledger was being built. `tools/loop-status.py` rendered
them as peers, so its headline read `13 proposal(s)` when 4 were real, and
`1p/7f/0i` of `w1` dominated the only surface that answers whether the loop
works.

THE RULE THIS PINS: the readers SEGREGATE a colon-less weakness id — out of
the headline count, out of the per-source table, out of the `--awaiting` list
— into an explicitly labelled fixture section. They never delete it, never
rewrite it, and `--json` still carries every row: out of the way is not out
of the record. (The ledger's own §4 lookup (docs/idea/11-agentic-loop-contract.md)
refuses unresolvable ids at write
time since 2026-08-16, so NEW placeholders cannot be filed; this covers the
nine that predate that wall.)

CI-safe: a tmp sqlite ledger and a stubbed weakness reader. No live wing.db,
no network. The only git the reader touches is `rev-parse HEAD` in this repo.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
READER = REPO / "tools" / "loop-status.py"


@pytest.fixture()
def reader(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("_loop_status_gate", READER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    db = tmp_path / "wing.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE loop_proposals (
            id INTEGER PRIMARY KEY, uuid TEXT, weakness_id TEXT,
            intent_class TEXT, proposer_id TEXT, target_paths TEXT,
            diff_text TEXT, requires_operator INTEGER DEFAULT 0,
            attempt_n INTEGER DEFAULT 1, created_at TEXT DEFAULT '2026-08-02'
        );
        CREATE TABLE loop_verdicts (
            id INTEGER PRIMARY KEY, proposal_id INTEGER, result TEXT,
            gate_set TEXT, tree_sha TEXT, created_at TEXT DEFAULT '2026-08-02'
        );
        """
    )
    # Seven fixture rows against `w1` (one passed — the live shape) and one
    # real proposal against `rem:REM-204`, also passed.
    for n in range(7):
        conn.execute(
            "INSERT INTO loop_proposals (uuid, weakness_id, intent_class, "
            "proposer_id, target_paths, diff_text) VALUES (?, 'w1', "
            "'version-pin-bump', 'agent:x', '[]', '')", (f"fixture-{n}",))
        conn.execute(
            "INSERT INTO loop_verdicts (proposal_id, result, tree_sha) "
            "VALUES (?, ?, 'f'*8)", (n + 1, "pass" if n == 0 else "fail"))
    conn.execute(
        "INSERT INTO loop_proposals (uuid, weakness_id, intent_class, "
        "proposer_id, target_paths, diff_text) VALUES ('real-0001', "
        "'rem:REM-204', 'version-pin-bump', 'agent:claude-opus-5', '[]', '')")
    conn.execute(
        "INSERT INTO loop_verdicts (proposal_id, result, tree_sha) "
        "VALUES (8, 'pass', NULL)")
    conn.commit()
    conn.close()

    mod.WING_DB = db
    # The weakness reader would import Bone and read the live estate; the gate
    # is about the LEDGER split, so the join column answers cleanly instead.
    mod._live_weakness_ids = lambda: ({"rem:REM-204"}, None)
    return mod


def test_the_headline_counts_only_real_work(reader):
    report = reader.collect()
    assert report["proposals"] == 1, (
        f"the headline says {report['proposals']} proposal(s); 7 of the 8 rows "
        f"are w1 fixtures and the headline is the loop's productivity claim"
    )
    assert report["fixture_proposals"] == 7, (
        "the fixtures left the report entirely — out of the way must not mean "
        "out of the record (that would be falsifying history)"
    )
    assert [s["source"] for s in report["sources"]] == ["rem"]
    assert [s["source"] for s in report["fixture_sources"]] == ["w1"]


def test_awaiting_lists_fixtures_below_the_work_never_among_it(reader):
    report = reader.awaiting()
    assert [r["weakness_id"] for r in report["rows"]] == ["rem:REM-204"], (
        f"--awaiting mixes fixture rows into the queue an operator acts on: "
        f"{[r['weakness_id'] for r in report['rows']]}"
    )
    assert len(report["fixture_rows"]) == 1 and \
        report["fixture_rows"][0]["weakness_id"] == "w1"
    assert all(not reader._is_placeholder(r["weakness_id"])
               for r in report["unlanded"]), (
        "a placeholder reached `unlanded` — that is the list red-status counts"
    )


def test_a_placeholder_is_exactly_a_colonless_id(reader):
    assert reader._is_placeholder("w1")
    assert reader._is_placeholder("w2")
    assert not reader._is_placeholder("rem:REM-204")
    assert not reader._is_placeholder("fee:hidden-fee-08")


def test_the_printed_fixture_note_names_what_and_why(reader, capsys):
    """The segregation must be legible, not silent — a count that quietly
    shrank from 13 to 4 without a printed reason is its own hidden fee."""
    reader._print_awaiting(reader.awaiting(), as_json=False)
    out = capsys.readouterr().out
    assert "fixture" in out and "w1" in out, (
        "the fixture rows are excluded without the printout saying so"
    )
