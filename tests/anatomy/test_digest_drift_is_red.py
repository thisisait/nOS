"""An image that changed under a running container without a converge is red.

Most FOSS images are unsigned and several are built here (`--build` from a
*_src_dir), so pinning digests per role is costly and partial. The honest
version (roadmap `digest-drift-red`): the converge RECORDS what each container
runs, and `tools/workload-digest-status.py` compares `docker inspect` against that
record. The converge writes; only the reader may call it drift or not.

Pinned here: the comparison (fixtures, no docker), UNKNOWN on a missing record,
the one red-status line, the recorder's source-commit mapping, and that the
converge records AFTER handlers flushed and on every pass that ran compose-up.
"""

from __future__ import annotations

import sys
import ast
import importlib.util
import json
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402
READER = REPO / "tools/workload-digest-status.py"
RECORDER = REPO / "tools/workload-digest-record.py"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _c(image_id, image="nos/keap:1.43-abc"):
    return {"image": image, "image_id": image_id, "repo_digests": [], "source": None}


RECORD = {
    "recorded_at": "2026-10-04T10:00:00+00:00",
    "containers": {
        "iiab-keap-1": _c("sha256:aaa"),
        "infra-traefik-1": _c("sha256:t1", "traefik:v3.7.13"),
        "iiab-old-1": _c("sha256:o1", "old:1"),
    },
}


def test_a_changed_image_id_is_drift_and_nothing_else_is():
    rd = _load(READER, "_digest_status")
    live = {
        "iiab-keap-1": _c("sha256:bbb"),            # swapped under the container
        "infra-traefik-1": _c("sha256:t1", "traefik:v3.7.13"),
        "iiab-new-1": _c("sha256:n1", "new:1"),     # started outside the converge
    }
    report = rd.compare(RECORD, live)
    assert [d["container"] for d in report["drift"]] == ["iiab-keap-1"]
    assert report["drift"][0]["recorded_id"] == "sha256:aaa"
    assert report["drift"][0]["live_id"] == "sha256:bbb"
    assert report["unrecorded"] == ["iiab-new-1"]
    assert report["gone"] == ["iiab-old-1"]
    assert report["ok"] == 1


def test_a_missing_or_torn_record_is_unknown_not_green(tmp_path):
    rd = _load(READER, "_digest_status")
    assert rd.collect(tmp_path / "absent.json", live={})["unknown"]
    torn = tmp_path / "torn.json"
    torn.write_text("{not json", encoding="utf-8")
    assert rd.collect(torn, live={})["unknown"]
    good = tmp_path / "rec.json"
    good.write_text(json.dumps(RECORD), encoding="utf-8")
    assert "unknown" not in rd.collect(good, live=dict(RECORD["containers"]))


def test_docker_unreachable_is_unknown(tmp_path, monkeypatch):
    rd = _load(READER, "_digest_status")
    good = tmp_path / "rec.json"
    good.write_text(json.dumps(RECORD), encoding="utf-8")
    monkeypatch.setattr(rd, "snapshot", lambda: None)
    assert rd.collect(good)["unknown"]


def test_red_status_says_it_in_one_line(monkeypatch):
    rs = _load(REPO / "tools/red-status.py", "_red_status_digest")
    report = {"sources_missing": [], "digest_drift": {"drift": [
        {"container": "iiab-keap-1", "image": "nos/keap:1", "recorded_id": "sha256:aaa1234567890",
         "live_id": "sha256:bbb1234567890"},
        {"container": "infra-redis-1", "image": "redis:8", "recorded_id": "sha256:r1",
         "live_id": "sha256:r2"},
    ], "recorded_at": RECORD["recorded_at"]}}
    lines = [ln for ln in rs.reds(report) if "converge" in ln and "image" in ln]
    assert len(lines) == 1, rs.reds(report)
    assert "iiab-keap-1" in lines[0] and "infra-redis-1" in lines[0]
    assert rs.reds({"sources_missing": [], "digest_drift": {"drift": []}}) == []


def test_red_status_reads_the_reader(monkeypatch):
    rs = _load(REPO / "tools/red-status.py", "_red_status_digest2")
    assert hasattr(rs, "digest_drift"), "red-status does not ask digest-status"
    monkeypatch.setattr(rs, "_digest_report", lambda: {"unknown": "no record"})
    assert rs.digest_drift() is None   # → sources_missing → UNKNOWN line


def test_the_recorder_names_the_source_commit_of_a_local_build(tmp_path):
    rec = _load(RECORDER, "_digest_record")
    srcs = rec.parse_srcs(["nos/keap=/k", "ghcr.io/pazny/nos-forum-web=/f", "localhost:5000/x=/x"])
    assert rec.repo_of("nos/keap:1.43-abc") == "nos/keap"
    assert rec.repo_of("localhost:5000/x") == "localhost:5000/x"
    assert rec.repo_of("ghcr.io/pazny/nos-forum-web:v0.1.0") == "ghcr.io/pazny/nos-forum-web"
    assert rec.repo_of("redis@sha256:abc") == "redis"
    assert srcs[rec.repo_of("localhost:5000/x:2")] == "/x"


def test_the_reader_writes_nothing():
    tree = ast.parse(READER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"write_text", "write_bytes", "replace", "unlink", "mkdir"}, node.attr
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "open":
            assert not any(isinstance(a, ast.Constant) and "w" in str(a.value) for a in node.args[1:])
        if isinstance(node, ast.List):
            argv = [e.value for e in node.elts if isinstance(e, ast.Constant)]
            assert not {"run", "pull", "exec", "rm", "restart", "stop", "compose"} & set(argv), argv


def _record_task(play):
    for i, t in enumerate(play.get("post_tasks") or []):
        if "workload-digest-record.py" in json.dumps(t):
            return i, t
    return None, None


def test_the_converge_records_after_handlers_on_every_compose_pass():
    play = yaml.safe_load((REPO / "main.yml").read_text(encoding="utf-8"))[0]
    i, task = _record_task(play)
    # post_tasks run after the tasks-section handler flush, so a handler that
    # recreates a container is inside the record, not a false drift.
    assert task is not None, "no post_task runs tools/workload-digest-record.py"
    tags = set(task.get("tags") or [])
    # compose-up tasks are tagged `always`; --skip-tags stacks skips both.
    assert {"always", "stacks"} <= tags, tags
    argv = task["ansible.builtin.command"]["argv"]
    assert "{{ nos_workload_digests_file }}" in argv
    # the reader's default path IS the declared one
    cfg = ni.default_config()
    rd = _load(READER, "_digest_status3")
    assert cfg["nos_workload_digests_file"].endswith("/.nos/" + rd.RECORD.name)
    # every locally built image the roles declare carries a --src
    for repo in ("nos/keap=", "nos/face=", "nos/superset=", "nos/postgis=", "{{ nos_forum_image }}="):
        assert any(repo in a for a in argv), f"{repo} has no --src: its source commit goes unrecorded"


def test_a_container_gone_between_ps_and_inspect_is_retried(monkeypatch):
    """A Pulse/backup container exiting mid-read failed the whole inspect, the
    recorder exited 1 and the converge failed. One fresh `ps` absorbs it."""
    rd = _load(READER, "_digest_status_race")
    calls = {"ps": 0}

    def fake(*args):
        if args[0] == "ps":
            calls["ps"] += 1
            return "a b" if calls["ps"] == 1 else "a"
        if args[0] == "inspect":
            return None if "b" in args else "/infra-redis-1\tsha256:1\tredis:7"
        return 'sha256:1\t["redis@sha256:x"]'

    monkeypatch.setattr(rd, "_docker", fake)
    assert rd.snapshot()["infra-redis-1"]["image_id"] == "sha256:1"
