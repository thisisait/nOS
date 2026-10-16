"""Gate: a confirmed blank leaves ~/.nos/blank-runs.jsonl, and a reader reads it.

The release gate is "a blank since the last tag + nos-smoke --strict", and on
2026-10-16 the only way to find the last blank was grepping RELEASE.md. Runs the
start task (main.yml) + tasks/post-smoke.yml through real Ansible with a temp
HOME and a fake nos-smoke that fails strict: the record must still be written.
"""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
START = "[Blank] Record that a confirmed blank started"
FAKE_SMOKE = "import sys\nprint('\\u274c 3 / 4 OK  \\u00b7  1 failed  \\u00b7  0 unreachable')\nsys.exit(1)\n"


def _start_task() -> dict:
    play = yaml.safe_load((REPO / "main.yml").read_text())[0]
    hits = [t for t in play["tasks"] if t.get("name") == START]
    assert hits, f"main.yml has no task {START!r}: a blank writes no record"
    return hits[0]


def _converge(tmp_path: Path, removing: bool) -> subprocess.CompletedProcess:
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/nos-smoke.py").write_text(FAKE_SMOKE)
    play = [{"hosts": "localhost", "gather_facts": False, "connection": "local",
             "vars": {"nos_removing": removing, "nos_confirmed": True, "nos_leaving": False,
                      "nos_smoke_strict": True, "nos_deployed_ref": "abc123",
                      "nos_docker_ready": True,
                      "ansible_facts": {"env": {"HOME": str(tmp_path)}}},
             "tasks": [_start_task(),
                       {"ansible.builtin.import_tasks": str(REPO / "tasks/post-smoke.yml")}]}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    return subprocess.run(["ansible-playbook", "-i", "localhost,", str(tmp_path / "play.yml")],
                          capture_output=True, text=True, cwd=tmp_path)


def _blank_line(home: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.syspath_prepend(str(REPO / "tools"))
    spec = importlib.util.spec_from_file_location("estate_status", REPO / "tools/estate-status.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["estate_status"] = mod
    spec.loader.exec_module(mod)
    res = mod.Result()
    mod.axis_blank(res)
    (line,) = [x for x in res.lines if x.axis == "blank"]
    return mod, line


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="runs through real Ansible")
def test_a_blank_whose_smoke_fails_still_leaves_its_record(tmp_path, monkeypatch):
    r = _converge(tmp_path, removing=True)
    assert r.returncode != 0, "a strict smoke at 3/4 must still fail the run"
    rows = [json.loads(x) for x in (tmp_path / ".nos/blank-runs.jsonl").read_text().splitlines()]
    assert rows[0]["finished"] is None and rows[0]["nos_commit"] == "abc123"
    last = rows[-1]
    assert last["started"] == rows[0]["started"] and last["finished"]
    assert last["failed"] is True and last["smoke_strict"] == {"passed": 3, "total": 4}
    mod, line = _blank_line(tmp_path, monkeypatch)
    assert line.state == mod.DISAGREE, line


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="runs through real Ansible")
def test_an_ordinary_converge_writes_no_blank_record(tmp_path):
    _converge(tmp_path, removing=False)
    assert not (tmp_path / ".nos/blank-runs.jsonl").exists()


def test_no_record_is_unknown_never_green(tmp_path, monkeypatch):
    mod, line = _blank_line(tmp_path, monkeypatch)
    assert line.state == mod.UNREADABLE and "UNKNOWN" in line.detail


def test_a_blank_that_never_finished_is_red(tmp_path, monkeypatch):
    (tmp_path / ".nos").mkdir()
    (tmp_path / ".nos/blank-runs.jsonl").write_text(json.dumps(
        {"started": "2026-10-09T08:00:00Z", "finished": None, "nos_commit": "x",
         "failed": None, "smoke_strict": None}) + "\n")
    mod, line = _blank_line(tmp_path, monkeypatch)
    assert line.state == mod.DISAGREE and "never finished" in line.detail


def test_a_clean_strict_blank_is_green_with_its_age(tmp_path, monkeypatch):
    (tmp_path / ".nos").mkdir()
    (tmp_path / ".nos/blank-runs.jsonl").write_text(json.dumps(
        {"started": "2026-10-09T08:00:00Z", "finished": "2026-10-09T09:00:00Z",
         "nos_commit": "x", "failed": False, "smoke_strict": {"passed": 6, "total": 6}}) + "\n")
    mod, line = _blank_line(tmp_path, monkeypatch)
    assert line.state == mod.OK and "6/6" in line.detail and "ago" in line.detail
