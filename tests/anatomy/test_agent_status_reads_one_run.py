"""agent-status.py --run: one Wing run for the thalamus's read_run (iris-agent-dendrogram inc.1).

WHY. read_run draws what this reader hands it, so the reader must hand the session, its
threads, iterations and events by actor_action_id, keep the agent's free text (messages,
tool output) behind, and say UNKNOWN, never an empty run, when wing.db cannot be read.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
READER = REPO / "tools" / "agent-status.py"
RUN = "5e2a9c41-7b3d-4f6e-8a1c-2d3e4f5a6b7c"


def _run(home: pathlib.Path) -> dict:
    r = subprocess.run([sys.executable, str(READER), "--json", "--run", RUN], capture_output=True, text=True,
                       env={**os.environ, "HOME": str(home)}, timeout=60, check=False)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_one_run_leaves_its_free_text_behind(tmp_path):
    db = tmp_path / "wing" / "app" / "data" / "wing.db"
    db.parent.mkdir(parents=True)
    c = sqlite3.connect(db)
    c.executescript("""
        CREATE TABLE agent_sessions (uuid, agent_name, status, stop_reason, outcome_result, error_json,
            started_at, ended_at, tokens_input, tokens_output);
        CREATE TABLE agent_threads (id INTEGER PRIMARY KEY, uuid, session_uuid, parent_thread_uuid, agent_name, role,
            status, stop_reason, started_at, ended_at, tokens_input, tokens_output);
        CREATE TABLE agent_iterations (session_uuid, iteration, grader_result, grader_feedback, tokens_input,
            tokens_output, created_at);
        CREATE TABLE events (id INTEGER PRIMARY KEY, ts, type, task, result_json, actor_action_id);
    """)
    c.execute("INSERT INTO agent_sessions VALUES (?, 'conductor', 'terminated', 'end_turn', 'satisfied', NULL,"
              " '2026-10-20T07:00:00+00:00', NULL, 10, 2)", (RUN,))
    c.execute("INSERT INTO agent_threads VALUES (1, 't1', ?, NULL, 'conductor', 'primary', 'terminated', NULL,"
              " '2026-10-20 07:00:00', NULL, NULL, NULL)", (RUN,))
    c.execute("INSERT INTO agent_iterations VALUES (?, 0, 'satisfied', 'secret feedback', 1, 1, '2026-10-20')", (RUN,))
    c.execute("INSERT INTO events VALUES (1, 'ts', 'agent_tool_result', 'agent:conductor/tool:x', ?, ?)",
              (json.dumps({"tool_use_id": "u1", "is_error": True, "content": "secret output"}), RUN))
    c.execute("INSERT INTO events VALUES (2, 'ts', 'agent_message', 'agent:other/llm.call.1', '{}', 'another-run')")
    c.commit()
    c.close()
    got = _run(tmp_path)
    assert got["session"]["agent_name"] == "conductor" and got["session"]["errored"] == 0
    assert [t["uuid"] for t in got["threads"]] == ["t1"]
    assert got["iterations"][0]["grader_result"] == "satisfied"
    assert got["events"] == [{"id": 1, "ts": "ts", "type": "agent_tool_result", "task": "agent:conductor/tool:x",
                              "tool_use_id": "u1", "is_error": True}]
    assert "secret" not in json.dumps(got)


def test_an_unreadable_ledger_is_unknown(tmp_path):
    assert "UNKNOWN" in _run(tmp_path)["error"]
