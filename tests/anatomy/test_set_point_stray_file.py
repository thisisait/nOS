"""A set-point the one-path rule ignores is red, and a writer never falls back past
a settings dir it cannot enter (mini 11-02: Wing wrote ~/.nos/halt, Pulse read
settings/halt, both said success). Rule itself: test_set_points_resolve_one_path.py.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
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


def _locked(tmp_path: Path, which: str) -> tuple[Path, Path, Path]:
    home, parent = tmp_path / "home", tmp_path / "nos"
    (parent / "settings").mkdir(parents=True)
    home.mkdir()
    return home, parent / "settings", (parent / "settings" if which == "settings" else parent)


def _moved(src: Path, sdir: Path, tmp_path: Path) -> Path:
    dst = tmp_path / src.name
    dst.write_text(src.read_text(encoding="utf-8").replace(DIR, str(sdir)), encoding="utf-8")
    return dst


@pytest.mark.skipif(os.geteuid() == 0, reason="root enters a 000 dir")
@pytest.mark.parametrize("locked", ["settings", "parent"])
def test_wing_refuses_a_halt_it_cannot_reach(tmp_path, locked):
    if not shutil.which("php"):
        pytest.skip("php not installed: Wing's writer is unchecked here")
    home, sdir, lock = _locked(tmp_path, locked)
    php = _moved(REPO / "files/anatomy/wing/app/Model/PulseRepository.php", sdir, tmp_path)
    code = (f'require "{php}"; $r = (new ReflectionClass(App\\Model\\PulseRepository::class))'
            '->newInstanceWithoutConstructor(); echo App\\Model\\PulseRepository::haltFile(), "\\n";'
            ' try { $r->emergencyHaltAll("op"); echo "WROTE"; } catch (RuntimeException $e) { echo "REFUSED"; }')
    lock.chmod(0)
    try:
        r = subprocess.run(["php", "-d", "display_errors=0", "-r", code], capture_output=True,
                           env={"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}, text=True, timeout=30)
    finally:
        lock.chmod(0o755)
    assert r.stdout.splitlines() == [str(sdir / "halt"), "REFUSED"], (r.stdout, r.stderr)
    assert not (home / ".nos").exists(), "Wing fell back to ~/.nos past a dir it cannot enter"


@pytest.mark.skipif(os.geteuid() == 0, reason="root enters a 000 dir")
def test_every_reader_keeps_the_settings_path_past_a_locked_parent(tmp_path, monkeypatch):
    home, sdir, lock = _locked(tmp_path, "parent")
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    lockfile = _moved(REPO / "files/anatomy/scripts/agent-run-lock.sh", sdir, tmp_path)
    sys.path.insert(0, str(REPO / "files/anatomy/pulse"))
    try:
        daemon = importlib.import_module("pulse.daemon")
    finally:
        sys.path.remove(str(REPO / "files/anatomy/pulse"))
    red = _red_status(monkeypatch, sdir, home)
    monkeypatch.setattr(daemon, "SETTINGS_DIR", str(sdir))
    lock.chmod(0)
    try:
        got = {"agent-run-lock.sh": subprocess.run(
            ["bash", "-c", f'source "{lockfile}"; printf %s "$NOS_LOOPS_PAUSED_FILE"'],
            env=env, capture_output=True, text=True, timeout=30).stdout,
            "pulse daemon": daemon.set_point_file("NOS_LOOPS_PAUSED_FILE"),
            "red-status": str(red.set_point_file("NOS_LOOPS_PAUSED_FILE"))}
    finally:
        lock.chmod(0o755)
    assert got == dict.fromkeys(got, str(sdir / "loops-paused")), got


@pytest.mark.skipif(os.geteuid() == 0, reason="root enters a 000 dir")
@pytest.mark.parametrize("locked", ["settings", "parent"])
def test_red_status_names_a_settings_dir_it_cannot_reach(tmp_path, monkeypatch, locked):
    home, sdir, lock = _locked(tmp_path, locked)
    mod = _red_status(monkeypatch, sdir, home)
    lock.chmod(0)
    try:
        lines = mod.reds({"stray_set_points": mod.stray_set_points()})
    finally:
        lock.chmod(0o755)
    assert any("cannot reach the set-points" in ln for ln in lines), lines
