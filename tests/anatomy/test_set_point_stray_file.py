"""A set-point the one-path rule ignores is red, and a writer never falls back past
a settings dir it cannot enter (mini 11-02: Wing wrote ~/.nos/halt, Pulse read
settings/halt, both said success). Rule itself: test_set_points_resolve_one_path.py.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DIR = "/var/lib/nos/settings"


def _red_status(monkeypatch, sdir: Path, home: Path):
    spec = importlib.util.spec_from_file_location("_red_stray", REPO / "tools/red-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "SETTINGS_DIR", str(sdir))
    monkeypatch.setenv("HOME", str(home))
    for var in ("NOS_HALT_FILE", "NOS_LOOPS_PAUSED_FILE"):
        monkeypatch.delenv(var, raising=False)
    return mod


def test_red_status_names_the_halt_in_the_path_not_taken(tmp_path, monkeypatch):
    sdir, home = tmp_path / "settings", tmp_path / "home"
    (home / ".nos").mkdir(parents=True)
    sdir.mkdir()
    (sdir / "halt").write_text("{}\n")
    (home / ".nos" / "halt").write_text("{}\n")  # left from before the settings dir
    mod = _red_status(monkeypatch, sdir, home)
    lines = mod.reds({"stray_set_points": mod.stray_set_points()})
    assert any(str(home / ".nos" / "halt") in ln and "stray" in ln for ln in lines), lines
    assert not any(str(sdir / "halt") in ln.split(";")[0] for ln in lines), lines


@pytest.mark.skipif(os.geteuid() == 0, reason="root enters a 000 dir")
@pytest.mark.parametrize("locked", ["settings", "parent"])
@pytest.mark.parametrize("argv", [["halt"], ["loops", "pause"]])
def test_a_writer_refuses_an_unreachable_settings_dir(tmp_path, locked, argv):
    home, parent = tmp_path / "home", tmp_path / "nos"
    sdir = parent / "settings"
    home.mkdir()
    sdir.mkdir(parents=True)
    script = tmp_path / "nos.sh"
    script.write_text((REPO / "tools/nos").read_text(encoding="utf-8").replace(DIR, str(sdir)))
    lock = sdir if locked == "settings" else parent
    lock.chmod(0)
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "NOS_MEDULLA": str(tmp_path / "no-medulla")}
    try:
        r = subprocess.run(["bash", str(script), *argv], env=env, capture_output=True, text=True, timeout=30)
    finally:
        lock.chmod(0o755)
    assert r.returncode != 0 and "cannot reach the set-points" in r.stderr, (r.returncode, r.stdout, r.stderr)
    assert not (home / ".nos").exists(), "fell back to ~/.nos past a dir it cannot enter"
