"""A loop manifest generates its pulse job — the OTHER output the ratified
loop-definition-model names. tools/loop-graph-gen.py draws the manifest for the
face; tools/discover-pulse-catalog.py schedules the SAME manifest. One source,
two outputs. A loop with no cadence/run is graph-only and schedules nothing.
"""
import importlib.util
import json
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _disc():
    spec = importlib.util.spec_from_file_location(
        "discover_pulse_catalog", REPO / "files/anatomy/scripts/discover-pulse-catalog.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_a_loop_with_cadence_and_run_generates_a_job():
    d = _disc()
    m = yaml.safe_load((REPO / "files/anatomy/loops/news-scout.loop.yml").read_text(encoding="utf-8"))
    jobs = d._loop_pulse_block(m).get("jobs")
    assert jobs and len(jobs) == 1
    j = jobs[0]
    assert j["name"] == m["id"]
    assert j["command"] == m["run"]  # run → command, verbatim
    assert j["schedule"] == m["trigger"]["cadence"]  # cadence → schedule
    assert j["category"] == "knowledge" and j["max_concurrent"] == 1


def test_a_graph_only_loop_is_not_scheduled():
    d = _disc()
    assert d._loop_pulse_block({"id": "x", "trigger": {"cadence": "* * * * *"}}) == {}  # no run
    assert d._loop_pulse_block({"id": "x", "run": "/bin/true", "trigger": {}}) == {}    # no cadence


def test_discovery_surfaces_the_loop_job_with_tokens_expanded(monkeypatch, capsys):
    d = _disc()
    monkeypatch.setenv("NOS_PLAYBOOK_DIR", str(REPO))
    monkeypatch.setenv("NOS_GLOBAL_PASSWORD_PREFIX", "testprefix")
    assert d.main() == 0
    cat = json.loads(capsys.readouterr().out)
    loop = [c for c in cat if c["plugin_name"] == "loop" and c["job"]["name"] == "news-scout"]
    assert loop, "discover-pulse-catalog did not surface loop:news-scout"
    cmd = loop[0]["job"]["command"]
    assert "news-scout.py --to-keap" in cmd
    assert "{{" not in cmd, "the {{ playbook_dir }} token must be expanded (else pulse execs a literal → rc 127)"
