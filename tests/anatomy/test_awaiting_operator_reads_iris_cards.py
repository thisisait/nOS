"""Gate: an Iris card waiting in the thalamus ledger is in "what awaits a person".

Row iris-approvals-in-readers (2026-11-08). tools/awaiting-operator.py read wing.db
only, so a card asked in ledger.db reached nobody's list. The fixture is built from
the SCHEMA the thalamus itself creates (ledger.rs), not a copy of it.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LEDGER_RS = REPO / "files/anatomy/thalamus/thalamus/src/ledger.rs"


def _tool():
    spec = importlib.util.spec_from_file_location("_awaiting", REPO / "tools" / "awaiting-operator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ledger(path: Path) -> Path:
    schema = re.search(r'const SCHEMA: &str = r#"(.*?)"#;', LEDGER_RS.read_text(encoding="utf-8"), re.S).group(1)
    con = sqlite3.connect(path)
    con.executescript(schema)
    sessions = [("s-live", "test-alice", None, None), ("s-closed", "test-dave", "2026-11-08T10:00:00Z", "connection_closed"),
                ("s-done", "test-dave", "2026-11-08T09:00:00Z", "cleared")]
    for uuid, actor, ended, why in sessions:
        con.execute("INSERT INTO sessions (uuid, agent_name, agent_version, status, trigger, actor_id, trace_id, model_uri,"
                    " started_at, ended_at, stop_reason) VALUES (?, 'iris', 1, 'running', 'shell', ?, 't', 'm', '2026-11-08T08:00:00Z', ?, ?)",
                    (uuid, actor, ended, why))

    def ev(run, kind, tool, approval):
        con.execute("INSERT INTO events (ts, run_id, type, task, result_json) VALUES ('2026-11-08T08:30:00Z', ?, ?, ?, ?)",
                    (run, kind, f"iris/tool:{tool}", json.dumps({"approval": approval})))
    ev("s-live", "agent_approval_request", "files.move", "open-1")
    ev("s-live", "agent_approval_request", "row_edit", "decided-1")
    ev("s-live", "agent_approval_decision", "row_edit", "decided-1")
    ev("s-closed", "agent_approval_request", "propose_table_create", "open-2")
    ev("s-done", "agent_approval_request", "row_edit", "dead-1")  # a cleared session resumes never
    con.commit()
    con.close()
    return path


def test_an_open_iris_card_is_listed_and_a_decided_one_is_not(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_THALAMUS_LEDGER", str(_ledger(tmp_path / "ledger.db")))
    items, why = _tool().iris_approvals()
    assert why == ""
    cards = sorted(i["where"].rsplit("card ", 1)[1] for i in items)
    assert cards == ["open-1", "open-2"], items
    assert all(i["kind"] == "approval" for i in items)
    assert any("test-alice" in i["what"] and "files.move" in i["what"] for i in items)


def test_an_unreadable_ledger_is_unknown_not_empty(tmp_path, monkeypatch):
    bad = tmp_path / "ledger.db"
    bad.write_bytes(b"not a database")
    monkeypatch.setenv("NOS_THALAMUS_LEDGER", str(bad))
    items, why = _tool().iris_approvals()
    assert items is None and why
