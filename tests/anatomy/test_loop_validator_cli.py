"""A loop manifest is checked on its own, before anything schedules it.

`tools/loop-graph-gen.py --validate <file>` exits 0, or 1 with every reason on
stderr. The committed manifests pass; one fixture per rule is refused and the
reason names the rule. discover-pulse-catalog.py calls the same function.
"""
import copy
import pathlib
import subprocess
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
GEN = REPO / "tools/loop-graph-gen.py"
MANIFESTS = sorted((REPO / "files/anatomy/loops").glob("*.loop.yml"))

GOOD = {
    "id": "fixture-loop", "label": "x", "blurb": "x",
    "trigger": {"cadence": "17 */4 * * *"},
    "params": {"sources": [{"id": "a"}]},
    "steps": [{"id": "one", "runner": "tool", "for_each": "sources"},
              {"id": "two", "runner": "agent",
               "writes": [{"target": "keap:corpus"}, {"target": "roles/pazny.x/defaults/main.yml"}]}],
    "run": "{{ playbook_dir }}/tools/loops/repo-check.py",
}


def _validate(path):
    return subprocess.run([sys.executable, str(GEN), "--validate", str(path)],
                          capture_output=True, text=True, timeout=60)


def test_the_committed_manifests_are_valid():
    assert len(MANIFESTS) >= 4
    for path in MANIFESTS:
        r = _validate(path)
        assert r.returncode == 0, f"{path.name} refused: {r.stderr}"


def test_the_good_fixture_is_valid(tmp_path):
    p = tmp_path / "good.loop.yml"
    p.write_text(yaml.safe_dump(GOOD), encoding="utf-8")
    r = _validate(p)
    assert r.returncode == 0, r.stderr


def _bad_id(m): m["id"] = "Bad_Id"
def _sere(m): m["id"] = "sere"
def _no_trigger(m): m["trigger"] = {}
def _runner(m): m["steps"][0]["runner"] = "shell"
def _for_each(m): m["steps"][0]["for_each"] = "feeds"
def _dup_step(m): m["steps"][1]["id"] = "one"
def _cron(m): m["trigger"]["cadence"] = "every day at 7"
def _cron_range(m): m["trigger"]["cadence"] = "61 * * * *"
def _run_missing(m): m["run"] = "{{ playbook_dir }}/tools/loops/no-such-loop.py"
def _run_outside(m): m["run"] = "/bin/sh"
def _writes_root(m): m["steps"][1]["writes"].append({"target": "files/anatomy/loops/x.loop.yml"})


@pytest.mark.parametrize("mutate,rule", [
    (_bad_id, "not a slug"),
    (_sere, "reserved"),
    (_no_trigger, "trigger needs"),
    (_runner, "runner must be one of"),
    (_for_each, "not a declared param"),
    (_dup_step, "duplicate step id"),
    (_cron, "not a cron"),
    (_cron_range, "not a cron"),
    (_run_missing, "tools/loops/"),
    (_run_outside, "tools/loops/"),
    (_writes_root, "allowed roots"),
])
def test_each_rule_refuses_with_its_reason(tmp_path, mutate, rule):
    m = copy.deepcopy(GOOD)
    mutate(m)
    p = tmp_path / "bad.loop.yml"
    p.write_text(yaml.safe_dump(m), encoding="utf-8")
    r = _validate(p)
    assert r.returncode == 1, f"{mutate.__name__}: --validate accepted it (rc={r.returncode})"
    assert rule in r.stderr, f"{mutate.__name__}: reason does not name the rule: {r.stderr!r}"


def test_every_reason_is_reported_not_just_the_first(tmp_path):
    m = copy.deepcopy(GOOD)
    _runner(m)
    _dup_step(m)
    p = tmp_path / "bad.loop.yml"
    p.write_text(yaml.safe_dump(m), encoding="utf-8")
    r = _validate(p)
    assert r.returncode == 1
    assert "runner must be one of" in r.stderr and "duplicate step id" in r.stderr, r.stderr
