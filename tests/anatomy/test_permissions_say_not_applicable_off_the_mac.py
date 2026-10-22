"""tools/permission-status.py off the Mac: NOT APPLICABLE, plainly, exit 0.

On the DGX Spark the reader died with FileNotFoundError: 'log' and the `perms`
pane showed a traceback. TCC is Apple's; Linux has nothing to read and nothing
that can stall on a dialog. The honest answer is neither a traceback nor an
empty table (which reads as "nothing denied") — it is one row that says the
question does not apply here.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "permission-status.py"


def _load():
    spec = importlib.util.spec_from_file_location("_perm_off_mac", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_linux_is_not_applicable_and_nothing_is_probed(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setattr(mod.nos_host, "SYSTEM", "Linux")
    ran = []
    monkeypatch.setattr(mod, "probes", lambda: ran.append("probes") or [])
    monkeypatch.setattr(mod, "grants", lambda *a: ran.append("grants") or [])
    assert mod.main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["applicable"] is False and data["platform"] == "Linux"
    assert "no equivalent on Linux" in data["why"]
    assert ran == [], "nothing is probed on a host that has no TCC"
    assert mod.main([]) == 0
    assert capsys.readouterr().out.startswith("NOT APPLICABLE")


def test_the_pane_shows_one_row_not_an_empty_table():
    sys.path.insert(0, str(REPO / "tools"))
    from cc.panes import perms  # noqa: PLC0415
    rows = perms.build_rows({"applicable": False, "platform": "Linux", "why": "no TCC"})
    assert len(rows) == 1 and rows[0]["state"] == "N/A" and rows[0]["state"] != "OK"


def test_an_absent_unified_log_is_unknown_not_empty(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod.nos_host, "unified_log", lambda *a, **k: None)
    assert "error" in mod.grants()[0], "no log is not 'nothing was asked'"
