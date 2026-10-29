"""A container Docker keeps restarting is red, even while its healthcheck says healthy.

Measured 2026-10-29: Loki was OOM-killed and restarted every ~15 s for hours (741 restarts) and
red-status listed nothing: health said healthy between deaths. Executed: tools/container-status.py
against a fake `docker` that answers ps/inspect in Docker's own shapes, and red-status's wiring.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NOW = dt.datetime(2026, 10, 29, 6, 40, tzinfo=dt.timezone.utc)


def _mod():
    spec = importlib.util.spec_from_file_location("container_status", REPO / "tools/container-status.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["container_status"] = m
    spec.loader.exec_module(m)
    return m


def _docker(tmp_path, containers):
    data = tmp_path / "inspect.json"
    data.write_text(json.dumps(containers))
    exe = tmp_path / "docker"
    exe.write_text('#!/bin/sh\ncase "$1" in ps) echo a b c;; inspect) cat "%s";; esac\n' % data)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return str(exe)


def _c(name, restarts, started, health="healthy", restarting=False):
    return {"Name": "/" + name, "RestartCount": restarts,
            "State": {"Restarting": restarting, "OOMKilled": False, "ExitCode": 0,
                      "StartedAt": started, "Health": {"Status": health}}}


def test_a_healthy_looking_crash_loop_is_red_and_the_rest_is_not(tmp_path):
    m = _mod()
    docker = _docker(tmp_path, [
        _c("observability-loki-1", 741, "2026-10-29T06:32:44.818313Z"),   # restarted 8 min ago
        _c("infra-traefik-1", 0, "2026-10-29T06:30:00.0Z"),                # recreated by a converge
        _c("iiab-old-1", 2, "2026-10-26T01:00:00.123456789Z"),             # restarted days ago, steady
    ])
    report = m.collect(docker, now=NOW)
    assert report["sources_missing"] == []
    assert [c["name"] for c in report["looping"]] == ["observability-loki-1"]
    assert "741×" in m.summary(report)[0] and "healthy" in m.summary(report)[0]


def test_no_docker_is_unknown_not_quiet(tmp_path):
    report = _mod().collect(str(tmp_path / "absent-docker"), now=NOW)
    assert report["looping"] == [] and report["sources_missing"]


def test_red_status_lists_crash_loops():
    src = (REPO / "tools/red-status.py").read_text()
    assert '_sibling("container")' in src and 'report.get("crash_loops")' in src
