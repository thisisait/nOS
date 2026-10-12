"""Journey: Iris edits one roadmap cell only after the person approves, provably.

The thalamus (files/anatomy/thalamus) is the person's door to KEAP: the peer's
login names the person, every read and write goes to KEAP as them, and the only
write path is an approval the person gave. This walks it on the live estate:

  1. a turn on ~/.nos/thalamus.sock searches "roadmap" (the alias serve maps
     to NOS_ROADMAP_TABLE_ID) and proposes one title change
  2. the proposal shows exactly that cell, old -> new, and nothing is written yet
  3. the person approves
  4. a reader, not the thalamus, says it happened: KEAP holds the new title and
     the ledger holds the approve decision and a written tool result

The cell is put back by the undo (registered before the approval), and the probe
fails the next run if any roadmap title still carries the journey's marker.
The model chooses the tool calls, so a model that will not follow the turn fails
step 1 with what it said instead.
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import sqlite3
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import pytest
import yaml

from ..lib.residue import ResidueProbe

REPO = Path(__file__).resolve().parents[3]
SOCK = Path(os.environ.get("THALAMUS_SOCK", Path.home() / ".nos/thalamus.sock"))
MARK = "e2e-thalamus-"
# The id the role renders into the plist; read from its one source, not copied.
TABLE = os.environ.get("NOS_ROADMAP_TABLE_ID") or yaml.safe_load(
    (REPO / "roles/pazny.keap/defaults/main.yml").read_text())["keap_roadmap_table_id"]

sys.path.insert(0, str(REPO / "tools"))
import keap_api  # noqa: E402 — the estate's one KEAP resolver


def _status_reader():
    spec = importlib.util.spec_from_file_location("thalamus_status", REPO / "tools/thalamus-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _require_thalamus():
    if not SOCK.exists():
        pytest.skip(f"thalamus socket absent at {SOCK} (THALAMUS_SOCK overrides the path)")


def _get(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=keap_api.human_headers()), timeout=30) as r:
        return json.loads(r.read())


def _rows() -> list[dict]:
    base = f"{keap_api.human_base()}/api/tables/{urllib.parse.quote(TABLE, safe='')}/rows"
    return keap_api.paged(_get, base)["data"]["rows"]


def _marked() -> list[str]:
    """READER: roadmap rows whose title still carries this journey's marker."""
    return [r["id"] for r in _rows() if MARK in str((r.get("values") or {}).get("title", ""))]


RESIDUE_PROBES = (ResidueProbe("roadmap title edited by the thalamus journey", _marked),)


def _restore(row_id: str, title: str) -> None:
    keap_api.write_row(TABLE, {"slug": row_id, "title": title})


class Wire:
    """Newline-delimited JSON on the thalamus socket (nos_contract::wire)."""

    def __init__(self, path: Path):
        self.s = socket.socket(socket.AF_UNIX)
        self.s.settimeout(300)  # a local model's turn is slow, not hung
        self.s.connect(str(path))
        self.r = self.s.makefile("r", encoding="utf-8")

    def send(self, **m) -> None:
        self.s.sendall((json.dumps(m) + "\n").encode())

    def until_end(self) -> list[dict]:
        """Every message up to the turn's text or a refusal."""
        got = []
        for line in self.r:
            got.append(json.loads(line))
            if got[-1]["t"] in ("text", "refused"):
                return got
        raise AssertionError(f"the thalamus closed the connection mid-turn: {got}")


def _ledger_db() -> str:
    rows = {x["check"]: x for x in _status_reader().collect()}
    assert rows["ledger"]["state"] == "OK", rows["ledger"]
    return rows["ledger"]["source"]


def test_thalamus_writes_one_cell_only_after_approval(journey):
    marker = uuid.uuid4().hex[:10]
    with journey("thalamus_row_edit", residue_probes=RESIDUE_PROBES) as j:

        with j.step("pick_a_row") as s:
            rows = [r for r in _rows() if isinstance((r.get("values") or {}).get("title"), str) and r.get("id")]
            assert rows, f"no titled row in roadmap table {TABLE}"
            row = next((r for r in rows if r["values"].get("status") == "shipped"), rows[0])
            row_id, old = row["id"], row["values"]["title"]
            new = f"{old} [{MARK}{marker}]"
            s.note = row_id

        w = Wire(SOCK)
        with j.step("iris_proposes_the_edit") as s:
            w.send(t="turn", session=None, text=(
                f'Call search_rows with table "roadmap" and q "{row_id}". Then call propose_row_edit with '
                f'table "roadmap", row_id "{row_id}" and values {{"title": {json.dumps(new)}}}. Nothing else.'))
            got = w.until_end()
            session = next(m["session"] for m in got if m["t"] == "session")
            asks = [m for m in got if m["t"] == "approval_request"]
            assert len(asks) == 1, f"expected one approval request, got: {got}"
            approval, diff = asks[0]["approval"], asks[0]["component"]["props"]
            assert (diff["table"], diff["row_id"]) == (TABLE, row_id), diff
            assert diff["cells"] == [{"key": "title", "old": old, "new": new}], diff["cells"]
            assert [r["values"]["title"] for r in _rows() if r["id"] == row_id] == [old], "written before approval"
            s.note = f"approval={approval[:8]}"

        with j.step("the_person_approves") as s:
            # Registered before the write it undoes: a crash on the next line still restores.
            j.mutates("roadmap_title", row_id, lambda: _restore(row_id, old))
            w.send(t="approval_decision", approval=approval, decision="approve", note=None)
            got = w.until_end()
            assert got[-1]["t"] == "text" and got[-1]["text"].startswith("Approved: row"), got
            s.note = got[-1]["text"][:60]

        with j.step("a_reader_says_it_happened") as s:
            assert [r["values"]["title"] for r in _rows() if r["id"] == row_id] == [new], "KEAP lacks the approved title"
            with sqlite3.connect(f"file:{_ledger_db()}?mode=ro", uri=True) as db:
                ev = db.execute("SELECT type, result_json FROM events WHERE run_id = ? AND type IN "
                                "('agent_approval_decision', 'agent_tool_result') ORDER BY id", (session,)).fetchall()
            said = [json.loads(r) for t, r in ev if t == "agent_approval_decision"]
            assert [(d["approval"], d["decision"]) for d in said] == [(approval, "approve")], said
            results = [json.loads(r) for t, r in ev if t == "agent_tool_result"]
            assert {"approval": approval, "written": True, "row": row_id} in results, results
            s.note = "KEAP + ledger agree"
        w.s.close()
