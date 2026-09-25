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
    assert j["command"] == m["run"]
    assert " " not in j["command"].split("}}")[-1], (
        "loop run: is argv0; flags go in args: — a space after the path 400s Wing"
    )
    assert j["args"] == m.get("args") == ["--to-keap"]
    assert j["schedule"] == m["trigger"]["cadence"]
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
    by_name = {c["job"]["name"]: c["job"] for c in cat if c["plugin_name"] == "loop"}
    scout = by_name.get("news-scout")
    assert scout, "discover-pulse-catalog did not surface loop:news-scout"
    assert scout["command"].endswith("tools/loops/news-scout.py")
    assert scout.get("args") == ["--to-keap"]
    assert "{{" not in scout["command"], (
        "the {{ playbook_dir }} token must be expanded (else pulse execs a literal → rc 127)")
    check = by_name.get("repo-check")
    assert check, "discover-pulse-catalog did not surface loop:repo-check"
    assert check["command"].endswith("tools/loops/repo-check.py")
    assert check.get("args") in (None, [])
    assert "--apply" not in (check.get("args") or [])
    assert check["category"] == "platform"


def test_anatomy_graph_harvests_generated_loop_jobs():
    """The pulse catalog already globs *.loop.yml; anatomy-graph-gen.py did not.
    Face Runs replay walks anatomy pulse nodes, so loop:news-scout was
    scheduled and invisible on that screen at once."""
    spec = importlib.util.spec_from_file_location(
        "anatomy_graph_gen", REPO / "tools/anatomy-graph-gen.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    nodes, raw, writes = {}, [], []
    gen.harvest_pulse(nodes, raw, writes)
    for loop_id in ("news-scout", "repo-check"):
        nid = f"pulse:loop:{loop_id}"
        assert nid in nodes, (
            f"{nid} missing from anatomy harvest — JOB_SOURCES is still "
            "plugins+agents only. Runs replay cannot pick the generated job."
        )
        assert nodes[nid]["kind"] == "pulse"
        assert nodes[nid]["source"].endswith(f"loops/{loop_id}.loop.yml")


#: The three READERS repo-check was born with. Each exits 0 whatever it finds;
#: none may quietly disappear. Steps BEYOND these are allowed — `wording-coverage`
#: was added 2026-09-25 — but only if they cannot write (asserted below).
_REPO_CHECK_READERS = {"red-status", "estate-status", "forge-sync"}

#: Flags that would make any step of this loop change something.
_WRITE_FLAGS = ("--apply", "--push-github", "--confirm", "--write", "--force")


def test_repo_check_pulse_job_is_report_only():
    d = _disc()
    m = yaml.safe_load((REPO / "files/anatomy/loops/repo-check.loop.yml").read_text(encoding="utf-8"))
    j = d._loop_pulse_block(m)["jobs"][0]
    blob = " ".join([j["command"], *(j.get("args") or [])])
    for flag in _WRITE_FLAGS:
        assert flag not in blob, f"repo-check is report-only; {flag} is in its pulse command"
    ids = {s["id"] for s in m["steps"]}
    assert _REPO_CHECK_READERS <= ids, (
        f"a reader vanished from repo-check: {sorted(_REPO_CHECK_READERS - ids)}"
    )
