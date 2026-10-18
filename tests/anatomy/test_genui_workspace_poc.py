"""The genui workspace PoC, offline: a form, a table and a chart over one KEAP table.

WHY. Each piece (widget runs, aggregation, form submit, commit insert, table_changed,
the workspace reducers) has its own gate, but the PoC is the claim that they join:
a submit stores a row, and the two readers re-run and answer what KEAP now holds,
with no model call and a ledger that says who read and wrote what. This runs the
cargo script over the stateful fake (tests/serve.rs genui_workspace_poc), the
pupil's decode of the PoC layout, and checks poc.test.ts is in the vitest lane
(test_pupil_and_thalamus_lanes_run.py runs every face and pupil *.test.ts). genui I5i.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
POC = REPO / "state/fixtures/genui-workspace-poc"
THALAMUS = REPO / "files/anatomy/thalamus/thalamus"
PUPIL = REPO / "files/anatomy/pupil"


def test_the_poc_fixture_is_the_expenses_table_and_one_tab():
    schema = json.loads((POC / "expenses.schema.json").read_text(encoding="utf-8"))["data"]
    cols = {c["key"]: c for c in schema["schema"]["columns"]}
    assert (schema["id"], set(cols)) == ("expenses", {"when", "kind", "amount"})
    assert cols["kind"]["options"] == ["food", "travel", "tools"] and cols["amount"]["required"] is True
    assert len(json.loads((POC / "expenses.rows.json").read_text(encoding="utf-8"))) == 3
    layout = json.loads((POC / "workspace.json").read_text(encoding="utf-8"))
    assert [sorted(w["spec"]) for w in layout["workspaces"][0]["widgets"]] == [["rows"], ["chart"], ["form"]]
    assert (REPO / "files/anatomy/face/src/lib/iris/poc.test.ts").is_file()


def _cargo(cwd: pathlib.Path, *args: str) -> str:
    r = subprocess.run(["cargo", "test", "--locked", *args], cwd=cwd, capture_output=True, text=True, timeout=1800, check=False)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-6000:]
    return out


@pytest.mark.skipif(not shutil.which("cargo"), reason="cargo runs the PoC script")
def test_the_poc_script_runs_over_the_stateful_fake():
    out = _cargo(THALAMUS, "--test", "serve", "genui_workspace_poc")
    assert re.search(r"test genui_workspace_poc \.\.\. ok", out), out[-2000:]


@pytest.mark.skipif(not shutil.which("cargo"), reason="cargo runs the pupil's decoder")
def test_the_pupil_loads_the_poc_layout():
    out = _cargo(PUPIL / "src-tauri", "-p", "nos-pupil", "--no-default-features", "the_poc_workspace_decodes")
    assert re.search(r"the_poc_workspace_decodes \.\.\. ok", out), out[-2000:]
