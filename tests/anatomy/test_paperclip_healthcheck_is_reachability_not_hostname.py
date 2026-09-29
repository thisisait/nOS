"""Paperclip's healthcheck proves the bind is reachable, nothing more.

The hostname allow-list is written by post.yml, which runs AFTER the STRICT
health-wait. A healthcheck that needed the hostname allowed (curl -sf on a
403) could only go green on an estate that had already been converged once;
the first blank after it landed stalled at `devops: 4/5 FAILED: paperclip-1`
(2026-09-29). Run the rendered check with a stub curl: 403 is up, a refused
connection (curl prints 000) is down.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
TPL = REPO / "roles/pazny.paperclip/templates/compose.yml.j2"


def _test_cmd() -> str:
    env = jinja2.Environment(undefined=jinja2.Undefined)
    env.filters["urlencode"] = lambda v: str(v)
    text = env.from_string(TPL.read_text()).render(paperclip_domain="paperclip.example.eu", paperclip_version="v", paperclip_port=3100)
    svc = next(iter(yaml.safe_load(text)["services"].values()))
    kind, cmd = svc["healthcheck"]["test"]
    assert kind == "CMD-SHELL"
    return cmd


def _run(cmd: str, code: str, tmp_path: Path) -> int:
    (tmp_path / "curl").write_text(f"#!/bin/sh\nprintf '{code}'\n")
    (tmp_path / "hostname").write_text("#!/bin/sh\necho 172.23.0.7 172.30.0.43\n")
    for f in ("curl", "hostname"):
        (tmp_path / f).chmod(0o755)
    return subprocess.run(["sh", "-c", cmd], env={"PATH": f"{tmp_path}:/usr/bin:/bin"}).returncode


def test_a_403_before_the_hostname_is_registered_is_up(tmp_path):
    assert _run(_test_cmd(), "403", tmp_path) == 0


def test_a_refused_connection_is_down(tmp_path):
    assert _run(_test_cmd(), "000", tmp_path) == 1


def test_the_check_still_targets_the_published_interface():
    assert "hostname -i" in _test_cmd() and "localhost" not in _test_cmd()
