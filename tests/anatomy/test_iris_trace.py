"""tools/iris-trace.py shows one Iris turn as it happened, read from the thalamus ledger.

WHY. Live test 2026-10-18: the operator could see Iris's answer but not the calls
behind it, and agents must never open ledger.db themselves. The ledger here is built
from ledger.rs's own CREATE statements, read at test time, so a schema change that
the trace no longer reads fails this test rather than the operator's pane.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TRACE = REPO / "tools" / "iris-trace.py"
LEDGER_RS = REPO / "files/anatomy/thalamus/thalamus/src/ledger.rs"
RUN = "5f0c2a9e-1111-4222-8333-444455556666"


def _run(db: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "NOS_THALAMUS_LEDGER": str(db)}
    return subprocess.run([sys.executable, str(TRACE), *args], capture_output=True, text=True, env=env, timeout=30)


def _ledger(db: Path) -> None:
    schema = re.search(r'const SCHEMA: &str = r#"(.*?)"#;', LEDGER_RS.read_text(), re.S).group(1)
    con = sqlite3.connect(db)
    con.executescript(schema)
    now = datetime.now(timezone.utc)
    ts = lambda s: now.replace(second=s % 60, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")  # noqa: E731
    con.execute("INSERT INTO sessions (uuid, agent_name, agent_version, status, trigger, actor_id, trace_id, model_uri,"
                " started_at) VALUES (?, 'iris', 1, 'running', 'shell', 'alice', 'x', 'ollama://m', ?)", (RUN, ts(0)))
    long = "z" * 400
    events = [
        ("agent_session_start", None, {"model_uri": "ollama://m"}),
        ("agent_message", None, {"role": "person", "text": "kolik řádků má expenses?"}),
        ("agent_tool_use", "query_rows", {"args": {"table": "expenses", "q": long}}),
        ("agent_tool_result", "query_rows", {"error": "no table `expenses`; tables: Todo list (todos)"}),
        ("agent_tool_use", "list_tables", {"args": {}}),
        ("agent_tool_result", "list_tables", {"tables": [{"id": "todos", "rowCount": 3}], "hidden": []}),
        ("agent_approval_request", "propose_row_edit", {"approval": "a-1", "table": "todos"}),
        ("agent_approval_decision", "propose_row_edit", {"approval": "a-1", "decision": "reject", "note": "ne"}),
        ("agent_message", None, {"role": "iris", "text": "Todo list má 3 řádky.\nDalší řádek."}),
        ("agent_message", None, {"role": "thalamus", "text": "Stopped."}),
    ]
    for i, (kind, tool, body) in enumerate(events):
        con.execute("INSERT INTO events (ts, run_id, type, task, result_json, source, actor_id) VALUES (?,?,?,?,?,'thalamus','alice')",
                    (ts(i + 1), RUN, kind, "agent:iris" + (f"/tool:{tool}" if tool else ""), json.dumps(body)))
    con.commit()
    con.close()


def test_a_whole_turn_prints_in_order_and_a_missing_ledger_is_unknown(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    _ledger(db)
    p = _run(db, "--since", "10m")
    assert p.returncode == 0, p.stderr
    out = p.stdout
    want = ["kolik řádků má expenses?", "query_rows", '"table": "expenses"', "error: no table `expenses`",
            "list_tables ok", "propose_row_edit", "reject", "Todo list má 3 řádky.", "Stopped."]
    at = [out.find(w) for w in want]
    assert -1 not in at and at == sorted(at), f"out of order or missing {dict(zip(want, at))}:\n{out}"
    assert "5f0c2a9e" in out and "alice" in out, out
    assert "Další řádek" not in out, "Iris text is its first line only"
    assert "z" * 200 not in out, "a long argument is truncated"
    assert all(len(ln) < 260 for ln in out.splitlines()), out

    rows = [json.loads(ln) for ln in _run(db, "--json", "--session", "5f0c").stdout.splitlines()]
    assert [r["kind"] for r in rows][:3] == ["person", "tool_use", "tool_result"], rows
    assert _run(db, "--session", "deadbeef").stdout.strip() == "", "another session's turn is not shown"

    gone = _run(tmp_path / "nope.db")
    assert gone.returncode == 0 and gone.stdout.startswith("UNKNOWN"), (gone.returncode, gone.stdout, gone.stderr)
