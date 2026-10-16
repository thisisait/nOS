"""tools/septum-status.py walks a row to its client, and never reports green blind.

Offline only: rows come from a fixture or a read_live that raises — the reader's
live path is a KEAP RO GET this suite must never make.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "septum-status.py"
_spec = importlib.util.spec_from_file_location("septum_status", TOOL)
septum = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(septum)

ROWS = {
    "party": [{"slug": "alfa", "role": "client"}, {"slug": "me", "role": "own_firm"}],
    "invoice": [{"slug": "i1", "book_owner": "alfa"}, {"slug": "i2", "book_owner": None}],
    "invoice-line": [{"slug": "l1", "invoice": "i1"}, {"slug": "l2", "invoice": "i2"},
                     {"slug": "l3", "invoice": "gone"}],
    "journal-entry": [{"slug": "j1", "source": "i1"}],
    "posting": [{"slug": "p1", "entry": "j1"}],
}


def test_rows_walk_the_declared_path_to_their_client():
    st = septum.live(septum.load_defs(), ROWS)
    assert st["parties"] == {"client": 1, "own_firm": 1}
    # i2 names no book at all: unstamped, not "own firm's" (the own firm is a party too).
    assert st["tables"]["invoice"] == {"rows": 2, "not_a_client": 0, "orphans": 0,
                                         "unstamped": 1, "by_client": {"alfa": 1}}
    # l2 reaches i2 by its ref: its book is unknown too, one hop down.
    assert st["tables"]["invoice-line"] == {"rows": 3, "not_a_client": 0, "orphans": 1,
                                              "unstamped": 1, "by_client": {"alfa": 1}}
    assert st["tables"]["posting"]["by_client"] == {"alfa": 1}  # posting → entry → invoice → party
    assert st["tables"]["party"]["by_client"] == {"alfa": 1}


def test_missing_and_unresolved_scopes_are_red():
    red, warn = septum.declarations({"a": {}, "b": {"client_scope": "unresolved"},
                                     "c": {"client_scope": "personal", "visibility": "tier-users"},
                                     "d": {"client_scope": "rowRef:x"}})
    assert [r.split(":")[0] for r in red] == ["a", "b"]
    assert [w.split(":")[0] for w in warn] == ["c"]


def test_unreadable_keap_is_unknown_and_exit_zero(tmp_path, monkeypatch, capsys):
    def boom(_defs):
        raise ConnectionRefusedError("no KEAP")
    monkeypatch.setattr(septum, "read_live", boom)
    monkeypatch.setattr(sys, "argv", ["septum-status.py"])
    assert septum.main() == 0
    out = capsys.readouterr().out
    assert "live: UNKNOWN" in out and "OK" not in out.split("\n")[0]


def test_cli_reads_a_rows_file(tmp_path):
    f = tmp_path / "rows.json"
    f.write_text(json.dumps(ROWS), encoding="utf-8")
    r = subprocess.run([sys.executable, str(TOOL), "--rows-json", str(f), "--json"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["live"]["tables"]["invoice"]["by_client"] == {"alfa": 1}


def test_a_dangling_ref_is_an_orphan_and_never_green(tmp_path):
    # l3 points at an invoice that is gone: not "not a client's", an orphan offboarding would miss.
    st = septum.live(septum.load_defs(), ROWS)
    assert st["tables"]["invoice-line"]["orphans"] == 1
    assert st["tables"]["invoice-line"]["not_a_client"] == 0
    f = tmp_path / "rows.json"
    f.write_text(json.dumps(ROWS), encoding="utf-8")
    r = subprocess.run([sys.executable, str(TOOL), "--rows-json", str(f), "--json"],
                       capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout)
    assert out["verdict"] != "OK"
    assert any("invoice-line" in line and "orphan" in line for line in out["red"])


def test_live_visibility_must_equal_the_declared_one():
    # KEAP may apply visibility on create only: a def flipped to private later can stay open live.
    defs = {"device": {"visibility": "private"}, "invoice": {"visibility": "tier-managers"},
            "not-yet": {"visibility": "private"}}
    red = septum.visibility_drift(defs, {"device": "tier-users", "invoice": "tier-managers",
                                         "not-yet": None})
    assert len(red) == 1 and red[0].startswith("device:")
    assert "private" in red[0] and "tier-users" in red[0]


def test_drift_is_red_and_absent_visibility_is_unknown(tmp_path):
    f = tmp_path / "rows.json"
    f.write_text(json.dumps({**ROWS, "_visibility": {"device": "tier-users"}}), encoding="utf-8")
    r = subprocess.run([sys.executable, str(TOOL), "--rows-json", str(f), "--json"],
                       capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout)
    assert out["verdict"] == "RED" and any(x.startswith("device:") for x in out["red"])
    f.write_text(json.dumps(ROWS), encoding="utf-8")   # rows, but no table visibility read
    r = subprocess.run([sys.executable, str(TOOL), "--rows-json", str(f)],
                       capture_output=True, text=True, timeout=60)
    assert "visibility: UNKNOWN" in r.stdout


def test_unreadable_keap_leaves_visibility_unknown(monkeypatch, capsys):
    def boom(_defs):
        raise ConnectionRefusedError("no KEAP")
    monkeypatch.setattr(septum, "read_live", boom)
    monkeypatch.setattr(sys, "argv", ["septum-status.py"])
    assert septum.main() == 0
    assert "visibility: UNKNOWN" in capsys.readouterr().out


def test_unstamped_book_rows_are_said_apart(tmp_path):
    f = tmp_path / "rows.json"
    f.write_text(json.dumps(ROWS), encoding="utf-8")
    r = subprocess.run([sys.executable, str(TOOL), "--rows-json", str(f), "--json"],
                       capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout)
    assert any(w.startswith("invoice:") and "unstamped" in w for w in out["warn"])
