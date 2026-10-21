"""Journey: Iris draws one real agent run as a dendrogram (iris-agent-dendrogram inc.1).

Read-only. The newest finished run in Wing's ledger is the subject (nothing is spawned:
starting an agent is increment 2's start_agent, behind an approval). A turn on the
thalamus socket asks for read_run; the render must be one tree whose root is that run,
with one node per Wing thread, grader iteration and drawn event, as wing.db says,
capped at 200 with `hidden` holding the rest. The face's SVG of the same props is
pinned offline (face/src/lib/iris/dendrogram.test.ts).
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SOCK = Path(os.environ.get("THALAMUS_SOCK", Path.home() / ".nos/thalamus.sock"))
sys.path.insert(0, str(REPO / "tools"))
import _ledger_open  # noqa: E402 — the one read-only way into wing.db

# Events serve folds into another node (a tool result into its call) or leaves to the root.
FOLDED = ("agent_session_start", "agent_session_end", "agent_tool_result", "agent_grader_decision")


@pytest.fixture(autouse=True)
def _require_thalamus():
    if not SOCK.exists():
        pytest.skip(f"thalamus socket absent at {SOCK} (THALAMUS_SOCK overrides the path)")


def _wing() -> tuple[str, int, int]:
    """READER: the newest finished run, its thread count and the node count serve owes it."""
    conn, how = _ledger_open.open_ledger_ro()
    if conn is None:
        pytest.skip(f"wing.db UNKNOWN: {how}")
    with conn:
        row = conn.execute("SELECT uuid FROM agent_sessions WHERE status = 'terminated' ORDER BY started_at DESC LIMIT 1").fetchone()
        if row is None:
            pytest.skip("Wing holds no finished agent run yet")
        uuid = row["uuid"]
        threads = conn.execute("SELECT COUNT(*) FROM agent_threads WHERE session_uuid = ?", (uuid,)).fetchone()[0]
        iterations = conn.execute("SELECT COUNT(*) FROM agent_iterations WHERE session_uuid = ?", (uuid,)).fetchone()[0]
        types = conn.execute("SELECT type FROM events WHERE actor_action_id = ? ORDER BY id LIMIT 400", (uuid,)).fetchall()
        events = sum(t["type"] not in FOLDED for t in types)
    conn.close()
    return uuid, threads, 1 + threads + iterations + events


def test_iris_draws_one_wing_run_as_a_tree(journey):
    with journey("iris_draws_an_agent_run") as j:
        with j.step("pick_a_run") as s:
            uuid, threads, owed = _wing()
            s.note = f"{uuid[:8]} threads={threads} nodes={owed}"

        with j.step("iris_draws_it") as s:
            sock = socket.socket(socket.AF_UNIX)
            sock.settimeout(300)  # a local model's turn is slow, not hung
            sock.connect(str(SOCK))
            r = sock.makefile("r", encoding="utf-8")
            sock.sendall((json.dumps({"t": "turn", "session": None,
                                      "text": f'Call read_run with uuid "{uuid}". Nothing else.'}) + "\n").encode())
            got = []
            for line in r:
                got.append(json.loads(line))
                if got[-1]["t"] in ("text", "refused"):
                    break
            sock.close()
            trees = [m["component"]["props"] for m in got if m["t"] == "render" and m["component"]["kind"] == "dendrogram"]
            assert len(trees) == 1, f"expected one run tree, got: {got}"
            d = trees[0]
            assert d["root"] == uuid and [n["id"] for n in d["nodes"] if "parent" not in n] == [uuid], d
            assert len(d["nodes"]) == min(owed, 200) and len(d["nodes"]) + d["hidden"] >= owed, (len(d["nodes"]), d["hidden"], owed)
            assert sum(n["kind"] == "thread" for n in d["nodes"]) == min(threads, 199), d
            s.note = f"{len(d['nodes'])} nodes, {d['hidden']} hidden"
