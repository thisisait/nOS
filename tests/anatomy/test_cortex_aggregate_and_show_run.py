"""Contract v3's two read verbs do real work in Wing, not a typed absence.

`aggregate` must count/sum/average its input (optionally grouped) and `show`
must pass the rows through with a render spec. The coverage gate only asks that
a class exists; this asks what it returns, by running it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"

pytestmark = pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")

ROWS = [{"track": "a", "h": 1}, {"track": "a", "h": "2"}, {"track": "b", "h": 5}, {"track": "b"}]


def run(handler: str, params: dict, rows: list | None, tmp_path: Path) -> dict:
    files = ["CortexStageResult", "ResolvedStage", "CortexContext",
             "Handler/CortexHandlerInterface", f"Handler/{handler}"]
    requires = "\n".join(f"require '{WING}/app/Cortex/{f}.php';" for f in files)
    offered = "true" if rows is not None else "false"
    probe = tmp_path / "probe.php"
    probe.write_text(textwrap.dedent(f"""\
        <?php
        {requires}
        $h = new App\\Cortex\\Handler\\{handler}();
        $p = json_decode('{json.dumps(params)}', true);
        $in = json_decode('{json.dumps(rows or [])}', true);
        $r = $h->execute(new App\\Cortex\\ResolvedStage(0, $h->opcode(), false, [], $p),
            new App\\Cortex\\CortexContext('t', 'default', 'cx', null, $in, {offered}));
        echo json_encode($r->toArray());
    """), encoding="utf-8")
    out = subprocess.run(["php", "-d", "error_reporting=E_ALL", str(probe)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and not out.stderr, out.stderr or out.stdout
    return json.loads(out.stdout)


def test_aggregate_counts_sums_and_averages(tmp_path: Path) -> None:
    assert run("AggregateHandler", {"op": "count"}, ROWS, tmp_path)["rows"] == [{"count": 4}]
    grouped = run("AggregateHandler", {"op": "sum", "by": "track", "y": "h"}, ROWS, tmp_path)
    assert grouped["rows"] == [{"track": "a", "sum": 3}, {"track": "b", "sum": 5}]
    assert grouped["meta"] == {"skipped": 1}, "a row without a number must be counted as skipped"
    avg = run("AggregateHandler", {"op": "avg", "y": {"value": "h"}}, ROWS, tmp_path)
    assert avg["rows"] == [{"avg": 8 / 3}]


def test_aggregate_refuses_what_it_cannot_compute(tmp_path: Path) -> None:
    for params in ({"op": "median", "y": "h"}, {"op": "sum"}):
        assert run("AggregateHandler", params, ROWS, tmp_path)["code"] == "nothing_to_operate_by"
    assert run("AggregateHandler", {"op": "count"}, None, tmp_path)["code"] == "nothing_to_operate_by"


def test_show_passes_rows_through_with_a_render_spec(tmp_path: Path) -> None:
    got = run("ShowHandler", {"kind": "chart", "chart": "bar", "x": "track", "y": "h"}, ROWS, tmp_path)
    assert got["rows"] == ROWS
    assert got["meta"] == {"render": {"kind": "chart", "chart": "bar", "x": "track", "y": "h"}}
    assert run("ShowHandler", {"kind": "hologram"}, ROWS, tmp_path)["code"] == "nothing_to_operate_by"
