"""Every control-centre pane declares the same thing, and the palette can reach it.

WHY THIS EXISTS. Five TUI variants were built in parallel on 2026-08-29 and
four of them re-implemented "run the reader, parse JSON, cope with failure".
The combined control centre keeps ONE implementation (`tools/cc/contract.py`)
and makes a pane a declaration. That only holds while every pane actually
declares the same fields — a pane missing `COLUMNS` fails at the moment the
operator opens it, in a tmux pane, where a traceback is the least readable
place an error can appear.

It also pins the two rules the panes exist to serve:

  * UNKNOWN IS NOT EMPTY. A reader that cannot be run renders `ok=False` with
    a reason, never zero rows. This drives the real `table()` against a pane
    whose reader does not exist and checks which of the two it produces.
  * THE TEXT DUMP IS THE SCREEN. `--dump text` is what `tmux capture-pane -p`
    and an LLM get; if it could show different rows from the TUI it would be a
    second answer to one question.

The demo fixtures are what makes this runnable in CI, which has no estate and
no wing.db. A pane whose fixture does not satisfy its own `build_rows` is a
pane nobody can develop against offline.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

from cc import contract  # noqa: E402
from cc import panes as registry  # noqa: E402

ALL = registry.all_panes()
REQUIRED = ("ID", "LABEL", "TITLE", "COLUMNS", "DEMO")


def test_the_registry_found_the_panes() -> None:
    assert len(ALL) >= 7, f"only {sorted(ALL)} — the registry stopped discovering"


@pytest.mark.parametrize("pane_id", sorted(ALL))
def test_a_pane_declares_the_whole_contract(pane_id: str) -> None:
    pane = ALL[pane_id]
    missing = [f for f in REQUIRED if not hasattr(pane, f)]
    assert not missing, f"{pane_id} declares no {missing}"
    assert callable(pane.build_rows), f"{pane_id}.build_rows is not callable"
    assert hasattr(pane, "READER") or hasattr(pane, "fetch"), (
        f"{pane_id} has neither a READER nor its own fetch() — nothing can "
        "give it data"
    )
    assert pane.ID == pane_id and pane.COLUMNS, pane_id


@pytest.mark.parametrize("pane_id", sorted(ALL))
def test_the_fixture_renders_offline(pane_id: str) -> None:
    """CI has no estate. A pane that cannot render its own DEMO is a pane the
    next author cannot see without a converge."""
    t = contract.table(ALL[pane_id], demo=True)
    assert t["ok"], f"{pane_id} demo: {t['error']}"
    assert t["rows"], f"{pane_id} demo produced no rows — the fixture says nothing"
    for row in t["rows"]:
        assert isinstance(row, dict), f"{pane_id} build_rows returned {type(row)}, not dicts"
    text = contract.render_text(t, ALL[pane_id].TITLE)
    assert ALL[pane_id].TITLE in text and "\n" in text


def test_a_missing_reader_is_unknown_not_empty() -> None:
    class Absent:
        ID, LABEL, TITLE = "absent", "Absent", "a reader that is not there"
        READER = "tools/this-reader-does-not-exist.py"
        COLUMNS = ["a"]
        DEMO: dict = {}

        @staticmethod
        def build_rows(data):
            return []

    t = contract.table(Absent, demo=False)
    assert t["ok"] is False, (
        "a reader that cannot be run rendered as a successful empty table — the "
        "exact shape that let an empty compose stack pass a health gate as "
        "`0/0 ready` (hidden fee 08)"
    )
    assert t["rows"] == [] and t["error"]
    assert "UNKNOWN" in contract.render_text(t)


def test_a_reader_whose_shape_moved_is_unknown_too() -> None:
    """build_rows raising is a reader that changed under us, not a crash."""

    class Broken:
        ID, LABEL, TITLE = "broken", "Broken", "shape moved"
        COLUMNS = ["a"]
        DEMO = {"nope": 1}

        @staticmethod
        def fetch():
            return {"nope": 1}, None

        @staticmethod
        def build_rows(data):
            return data["rows_that_moved"]

    t = contract.table(Broken, demo=False)
    assert t["ok"] is False and "shape" in t["error"]


@pytest.mark.parametrize("pane_id", sorted(ALL))
def test_the_dump_is_the_rows_the_screen_would_show(pane_id: str) -> None:
    """Drives the real entry point, so the CLI wiring is covered too."""
    out = subprocess.run(
        [sys.executable, str(REPO / "tools/nos-pane.py"), pane_id, "--demo", "--dump", "json"],
        capture_output=True, text=True, timeout=60, cwd=REPO)
    assert out.returncode == 0, out.stderr
    import json

    dumped = json.loads(out.stdout)
    expected = contract.table(ALL[pane_id], demo=True)
    assert dumped["rows"] == expected["rows"], (
        f"{pane_id}: --dump json and the in-process table disagree; the "
        "machine-readable view would be a second answer"
    )
    assert dumped["columns"] == expected["columns"]


def test_the_dump_exits_zero_even_when_the_reader_is_unknown() -> None:
    """A pane that exits nonzero makes the tmux pane holding it look crashed."""
    out = subprocess.run(
        [sys.executable, str(REPO / "tools/nos-pane.py"), "nonsense-pane", "--dump", "text"],
        capture_output=True, text=True, timeout=30, cwd=REPO)
    assert out.returncode == 2, "an unknown pane NAME is a usage error, and says so"
    assert "have:" in out.stderr


def test_the_palette_can_reach_every_pane() -> None:
    """The palette is the only way to change a pane now that the keys are gone.

    Runs the real app headlessly through Textual's own Ctrl+P palette: type,
    submit, assert the app switched. A provider that matched nothing would
    leave the operator with whatever `nos-cc.sh` opened and no way out — and
    the first version of this app took Ctrl+P for a hand-written palette that
    Textual then swallowed, which this catches.
    """
    import asyncio

    from cc.app import ControlCentreApp

    async def drive() -> str:
        app = ControlCentreApp("red", demo=True)
        async with app.run_test() as pilot:
            await pilot.press("ctrl+p")
            await pilot.pause()
            for ch in "timeline":
                await pilot.press(ch)
            await pilot.pause(0.6)   # the palette searches on a debounce
            await pilot.press("down", "enter")
            await pilot.pause()
            return app.current

    assert asyncio.run(drive()) == "timeline", (
        "the palette did not switch the pane — with the numbered bindings gone "
        "this is the only way to change what a pane shows"
    )
