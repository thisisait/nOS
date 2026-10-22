"""tools/openhuman-status.py off the Mac: the macOS-only lines say N/A.

OpenHuman is a macOS desktop app (main.yml includes pazny.openhuman on Darwin
only). On the DGX Spark the reader printed `RED second Ollama — outside the one
Ollama: /usr/local/bin/ollama` against a /opt/homebrew prefix Linux never has:
a red nobody can act on. Off the Mac those two lines are N/A; on the Mac they
still read `lsof`, now through tools/nos_host.py.
"""

from __future__ import annotations

import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "openhuman-status.py"


def _load():
    spec = importlib.util.spec_from_file_location("_oh_off_mac", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_linux_says_not_applicable_for_the_mac_only_lines(monkeypatch, tmp_path):
    mod = _load()
    monkeypatch.setenv("NOS_OPENHUMAN_DIR", str(tmp_path))
    monkeypatch.setenv("NOS_OPENHUMAN_APP", str(tmp_path / "absent.app"))
    monkeypatch.setenv("NOS_OPENHUMAN_CASKROOM", str(tmp_path / "absent-cask"))
    monkeypatch.setattr(mod.nos_host, "SYSTEM", "Linux")
    monkeypatch.setattr(mod.nos_host, "lsof", lambda *a, **k: (_ for _ in ()).throw(AssertionError("lsof asked")))
    rows = {r["check"]: r["state"] for r in mod.collect()}
    assert rows["egress"] == mod.NA and rows["second Ollama"] == mod.NA
    assert mod.NA not in (mod.OK, mod.RED, mod.UNKNOWN)


def test_the_mac_still_reads_lsof_through_the_shim(monkeypatch, tmp_path):
    mod = _load()
    monkeypatch.setenv("NOS_OPENHUMAN_DIR", str(tmp_path))
    monkeypatch.setenv("NOS_OPENHUMAN_APP", str(tmp_path / "absent.app"))
    monkeypatch.setenv("NOS_OPENHUMAN_CASKROOM", str(tmp_path / "absent-cask"))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(mod.nos_host, "SYSTEM", "Darwin")
    asked = []
    monkeypatch.setattr(mod.nos_host, "lsof", lambda *a, **k: asked.append(a) or "")
    monkeypatch.setattr(mod, "_run", lambda argv: "")
    rows = {r["check"]: r["state"] for r in mod.collect()}
    assert any("ollama" in a for a in asked), "the second-Ollama listeners come from nos_host.lsof"
    assert rows["second Ollama"] == mod.OK
