"""Every reader of the halt and the loops pause resolves ONE path, by ONE rule.

On a Linux host with nos_system_user the medulla unit (ProtectHome) reads
/var/lib/nos/settings/{halt,loops-paused}, while `nos halt` / `nos loops pause`,
agent-run-lock.sh, Pulse's daemon, red-status and Wing each resolved the file on
their own, some only as ~/.nos/...: the shell wrote where the unit never read.
The rule, the same in every language: NOS_HALT_FILE / NOS_LOOPS_PAUSED_FILE wins;
else <dir>/{halt,loops-paused} when /var/lib/nos/settings exists; else ~/.nos/....
Each implementation names that directory exactly once, so the test moves that one
literal (or the module's SETTINGS_DIR) to a temp dir and asks the reader itself.
state.rs carries the same three cases as cargo tests (thalamus::state::tests).
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DIR = "/var/lib/nos/settings"
NAMES = {"NOS_HALT_FILE": "halt", "NOS_LOOPS_PAUSED_FILE": "loops-paused"}
CASES = ("env", "settings_dir", "home")
SHELL = {"tools/nos": REPO / "tools/nos", "agent-run-lock.sh": REPO / "files/anatomy/scripts/agent-run-lock.sh",
         "wing PulseRepository.php": REPO / "files/anatomy/wing/app/Model/PulseRepository.php"}


def _setup(tmp_path: Path, case: str) -> tuple[dict, Path, Path]:
    home, sdir = tmp_path / "home", tmp_path / "settings"
    home.mkdir()
    if case == "settings_dir":
        sdir.mkdir()
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    if case == "env":
        env.update({v: str(tmp_path / f"explicit-{n}") for v, n in NAMES.items()})
    return env, home, sdir


def _want(case: str, var: str, tmp_path: Path, home: Path, sdir: Path) -> str:
    return {"env": str(tmp_path / f"explicit-{NAMES[var]}"), "settings_dir": str(sdir / NAMES[var]),
            "home": str(home / ".nos" / NAMES[var])}[case]


def _moved(src: Path, sdir: Path, tmp_path: Path) -> Path:
    text = src.read_text(encoding="utf-8")
    assert text.count(DIR) == 1, f"{src.name}: the settings dir must be named exactly once, found {text.count(DIR)}"
    dst = tmp_path / src.name
    dst.write_text(text.replace(DIR, str(sdir)), encoding="utf-8")
    dst.chmod(0o755)
    return dst


def _shell_paths(name: str, script: Path, env: dict) -> dict:
    run = lambda *a: subprocess.run(list(a), env=env, capture_output=True, text=True, timeout=30)  # noqa: E731
    if name == "tools/nos":
        halt = run("bash", str(script), "halt", "--status").stdout
        loops = run("bash", str(script), "loops", "resume").stdout
        return {"NOS_HALT_FILE": halt.split("(", 1)[1].split(" absent)")[0],
                "NOS_LOOPS_PAUSED_FILE": loops.split("no sentinel at ", 1)[1].split(")")[0]}
    if name == "agent-run-lock.sh":
        out = run("bash", "-c", f'source "{script}"; printf %s "$NOS_LOOPS_PAUSED_FILE"').stdout
        return {"NOS_LOOPS_PAUSED_FILE": out}
    if not shutil.which("php"):
        pytest.skip("php not installed: Wing's reader is unchecked here")
    out = run("php", "-r", f'require "{script}"; echo App\\Model\\PulseRepository::haltFile();')
    assert out.returncode == 0, out.stderr
    return {"NOS_HALT_FILE": out.stdout}


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("name", sorted(SHELL))
def test_a_shell_or_php_reader_resolves_the_one_path(name, case, tmp_path):
    env, home, sdir = _setup(tmp_path, case)
    got = _shell_paths(name, _moved(SHELL[name], sdir, tmp_path), env)
    for var, path in got.items():
        assert path == _want(case, var, tmp_path, home, sdir), f"{name} [{case}] {var}"


def _py(name: str):
    if name == "pulse daemon":
        sys.path.insert(0, str(REPO / "files/anatomy/pulse"))
        try:
            return importlib.import_module("pulse.daemon")
        finally:
            sys.path.remove(str(REPO / "files/anatomy/pulse"))
    spec = importlib.util.spec_from_file_location("_red_sp", REPO / "tools/red-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("name", ["pulse daemon", "red-status"])
def test_a_python_reader_resolves_the_one_path(name, case, tmp_path, monkeypatch):
    env, home, sdir = _setup(tmp_path, case)
    mod = _py(name)
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert src.count(DIR) == 1, f"{name}: the settings dir must be named exactly once"
    monkeypatch.setattr(mod, "SETTINGS_DIR", str(sdir))
    for var in NAMES:
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for var in NAMES:
        assert str(mod.set_point_file(var)) == _want(case, var, tmp_path, home, sdir), f"{name} [{case}] {var}"
    if name == "pulse daemon":  # the hold itself reads that path
        halt = Path(_want(case, "NOS_HALT_FILE", tmp_path, home, sdir))
        halt.parent.mkdir(parents=True, exist_ok=True)
        halt.write_text("{}\n", encoding="utf-8")
        held = mod.paused_hold("backup:nightly")
        assert held is not None and str(halt) in held.stderr_tail, f"[{case}] pulse must hold on {halt}"
