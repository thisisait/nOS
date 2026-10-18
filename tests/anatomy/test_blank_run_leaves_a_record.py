"""Gate: a confirmed blank leaves ~/.nos/blank-runs.jsonl, and a reader reads it.

The release gate is "a blank since the last tag + nos-smoke --strict", and on
2026-10-16 the only way to find the last blank was grepping RELEASE.md. Runs the
start task (main.yml) + tasks/post-smoke.yml through real Ansible with a temp
HOME and a fake nos-smoke: the record must still be written, carry the strict
smoke a blank always runs ({ok, total, failed ids}, even without
nos_smoke_strict — 10-17 recorded null and the 32/32 was copied by hand), and it is closed
with the PLAY's outcome (a failure after smoke, e.g. first-login, is failed=true
with the task's name) by the callback ansible.cfg enables.
"""
import configparser
import importlib.util
import os
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
START = "[Blank] Record that a confirmed blank started"
#: A fake nos-smoke: probe rows as JSON under --strict --json (what the blank
#: records), else the summary line the verdict reads. GREEN = svc1 passes too.
_SMOKE = ("import json, sys\nGREEN = {}\n"
          "rows = [dict(id='svc%d' % i, ok=i > 1 or GREEN, skipped=False) for i in range(1, 5)]\n"
          "if '--strict' in sys.argv and '--json' in sys.argv:\n"
          "    print('\\n'.join(json.dumps(r) for r in rows))\n"
          "else:\n    print('%d / 4 OK' % sum(r['ok'] for r in rows))\nsys.exit(0 if GREEN else 1)\n")
FAKE_SMOKE, GREEN_SMOKE = _SMOKE.format(False), _SMOKE.format(True)


def _boom(name: str) -> dict:
    return {"name": name, "ansible.builtin.fail": {"msg": "boom"}}


def _callback_env() -> dict:
    """The callbacks ansible.cfg enables, so the gate also proves the wiring."""
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(REPO / "ansible.cfg")
    env = {k: v for k, v in os.environ.items() if k != "NOS_TELEMETRY_ENABLED"}
    env["ANSIBLE_CALLBACK_PLUGINS"] = str(REPO / cfg["defaults"]["callback_plugins"])
    env["ANSIBLE_CALLBACKS_ENABLED"] = cfg["defaults"]["callbacks_enabled"]
    return env


def _start_task() -> dict:
    play = yaml.safe_load((REPO / "main.yml").read_text())[0]
    hits = [t for t in play["tasks"] if t.get("name") == START]
    assert hits, f"main.yml has no task {START!r}: a blank writes no record"
    return hits[0]


def _converge(tmp_path: Path, removing: bool, confirmed: bool = True, leaving: bool = False,
              smoke: str = FAKE_SMOKE, before: tuple = (), after: tuple = ()) -> subprocess.CompletedProcess:
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/nos-smoke.py").write_text(smoke)
    play = [{"hosts": "localhost", "gather_facts": False, "connection": "local",
             "vars": {"nos_removing": removing, "nos_confirmed": confirmed, "nos_leaving": leaving,
                      "nos_deployed_ref": "abc123",
                      "nos_docker_ready": True,
                      "ansible_facts": {"env": {"HOME": str(tmp_path)}}},
             "tasks": [_start_task(), *before,
                       {"ansible.builtin.import_tasks": str(REPO / "tasks/post-smoke.yml")}, *after]}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    return subprocess.run(["ansible-playbook", "-i", "localhost,", str(tmp_path / "play.yml")],
                          capture_output=True, text=True, cwd=tmp_path, env=_callback_env())


def _rows(home: Path) -> list:
    return [json.loads(x) for x in (home / ".nos/blank-runs.jsonl").read_text().splitlines()]


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
    rows = _rows(tmp_path)
    assert rows[0]["finished"] is None and rows[0]["nos_commit"] == "abc123"
    last = rows[-1]
    assert last["started"] == rows[0]["started"] and last["finished"]
    assert last["failed"] is True and last["smoke_strict"] == {"ok": 3, "total": 4, "failed": ["svc1"]}
    assert last["failed_task"] == "[smoke] Fail the run on the smoke verdict"
    mod, line = _blank_line(tmp_path, monkeypatch)
    assert line.state == mod.DISAGREE and "3/4" in line.detail and "svc1" in line.detail, line


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="runs through real Ansible")
@pytest.mark.parametrize("where", ["after", "before"], ids=["after-smoke", "before-smoke"])
def test_a_blank_that_fails_outside_smoke_records_the_failure(tmp_path, monkeypatch, where):
    name = f"[test] a task {where} smoke fails"
    r = _converge(tmp_path, removing=True, smoke=GREEN_SMOKE, **{where: (_boom(name),)})
    assert r.returncode != 0
    last = _rows(tmp_path)[-1]
    assert last["finished"] and last["failed"] is True and last["failed_task"] == name, last
    mod, line = _blank_line(tmp_path, monkeypatch)
    assert line.state == mod.DISAGREE and "FAILED" in line.detail, line


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="runs through real Ansible")
def test_a_clean_blank_closes_green(tmp_path, monkeypatch):
    r = _converge(tmp_path, removing=True, smoke=GREEN_SMOKE)
    assert r.returncode == 0, r.stdout
    last = _rows(tmp_path)[-1]
    assert last["finished"] and last["failed"] is False and last["failed_task"] is None, last
    assert last["smoke_strict"] == {"ok": 4, "total": 4, "failed": []}
    mod, line = _blank_line(tmp_path, monkeypatch)
    assert line.state == mod.OK, line


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="runs through real Ansible")
@pytest.mark.parametrize("kw", [{"removing": False}, {"removing": True, "confirmed": False},
                                {"removing": True, "leaving": True}], ids=["ordinary", "dry-run", "leave"])
def test_only_a_confirmed_staying_blank_writes_a_record(tmp_path, kw):
    _converge(tmp_path, **kw)
    assert not (tmp_path / ".nos/blank-runs.jsonl").exists()


def _write(home: Path, *lines: str) -> None:
    (home / ".nos").mkdir()
    (home / ".nos/blank-runs.jsonl").write_text("\n".join(lines) + "\n")


@pytest.mark.parametrize("body", ["[1, 2]", json.dumps(
    {"started": "2026-10-09T08:00:00Z", "finished": "2026-10-09T09:00:00Z", "nos_commit": "x",
     "failed": False, "smoke_strict": {"ok": 1}})], ids=["not-a-dict", "smoke-without-total"])
def test_a_malformed_record_is_unknown_not_a_crash(tmp_path, monkeypatch, body):
    _write(tmp_path, body)
    mod, line = _blank_line(tmp_path, monkeypatch)
    assert line.state == mod.UNREADABLE and "UNKNOWN" in line.detail


def test_a_blank_without_a_strict_smoke_is_not_green(tmp_path, monkeypatch):
    _write(tmp_path, json.dumps({"started": "2026-10-09T08:00:00Z", "finished": "2026-10-09T09:00:00Z",
                                 "nos_commit": "x", "failed": False, "smoke_strict": None}))
    mod, line = _blank_line(tmp_path, monkeypatch)
    assert line.state != mod.OK and "no strict smoke" in line.detail


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
         "nos_commit": "x", "failed": False, "smoke_strict": {"ok": 6, "total": 6, "failed": []}}) + "\n")
    mod, line = _blank_line(tmp_path, monkeypatch)
    assert line.state == mod.OK and "6/6" in line.detail and "ago" in line.detail


def test_a_finished_blank_with_a_red_strict_probe_is_not_green(tmp_path, monkeypatch):
    """The strict smoke is evidence, not the run's verdict: a blank can close
    failed=false while a probe is red, and the reader must say which."""
    _write(tmp_path, json.dumps({"started": "2026-10-09T08:00:00Z", "finished": "2026-10-09T09:00:00Z",
                                 "nos_commit": "x", "failed": False,
                                 "smoke_strict": {"ok": 31, "total": 32, "failed": ["gitea"]}}))
    mod, line = _blank_line(tmp_path, monkeypatch)
    assert line.state == mod.DISAGREE and "31/32" in line.detail and "gitea" in line.detail, line
