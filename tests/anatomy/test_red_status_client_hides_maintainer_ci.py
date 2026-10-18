"""A client host's red-status does not list the maintainer's CI as its own red.

Measured 2026-10-18 on the client host: 'CI on dev is failure' and 'CI on
master is failure' — GitHub runs nobody there can act on. The declared fact is
install_loops (the maintainer's development loops; profiles/core.yml turns it
off). Runs the real reader with a temp HOME and a stub `gh` that reports red CI.
"""
from __future__ import annotations

import json
import pathlib
import stat
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNS = [{"name": "CI", "conclusion": "failure", "status": "completed",
         "headSha": "bbbbbbbb", "createdAt": "2026-10-18T10:00:00Z"}]
WRAP = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("_red", sys.argv[1])
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
loops = sys.argv[2] == "maintainer"
mod._install_flags = lambda: {"install_loops": loops}
sys.argv = ["red-status.py", "--json"]
raise SystemExit(mod.main())
"""


def _read(tmp: pathlib.Path, role: str) -> dict:
    bin_ = tmp / "bin"
    bin_.mkdir(exist_ok=True)
    (tmp / "runs.json").write_text(json.dumps(RUNS))
    gh = bin_ / "gh"
    gh.write_text(f'#!/bin/sh\n[ "$1" = run ] && cat {tmp}/runs.json || echo "[]"\n')
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    py_dir = str(pathlib.Path(sys.executable).resolve().parent)
    r = subprocess.run([sys.executable, "-c", WRAP, str(REPO / "tools" / "red-status.py"), role],
                       capture_output=True, text=True, timeout=120, cwd=REPO,
                       env={"PATH": f"{bin_}:{py_dir}:/usr/bin:/bin", "HOME": str(tmp)})
    assert r.returncode == 0, f"a reader exits 0 always:\n{r.stderr[-2000:]}"
    return json.loads(r.stdout)


def test_a_client_host_has_no_ci_red(tmp_path):
    maintainer = _read(tmp_path, "maintainer")
    assert any(line.startswith("CI CI on dev") for line in maintainer["reds"]), (
        "fixture broken: the maintainer's reader did not see the stubbed red CI")
    client = _read(tmp_path, "client")
    assert not [line for line in client["reds"] if line.startswith("CI ")], client["reds"]
    assert not any("gh run list" in m for m in client["sources_missing"]), "skipped is not UNKNOWN"
    assert [i for i in client.get("info", []) if "CI" in i], "the skip left no info line"
