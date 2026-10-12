"""Anatomy CI gate — a Docker VM that is short of memory NOW is refused before any stack.

MEASURED 2026-10-12 08:09-08:20: a converge died at tasks/tofu-authentik.yml
(tofu plan, 10m21s, Authentik GET .../applications/hermes/ -> EOF). Inside the
VM /proc/pressure/memory read `full avg300=34.55` (a quiet VM reads ~0.1);
the night before it read 54.8 and `docker ps` took 10 s. The size check
(docker_min_memory_gib, test_a_small_docker_vm_is_refused_early.py) passed
both times: the VM was big enough on paper and starving in fact.

Pinned, offline (fixture PSI text, no docker): the parser reads the `full`
line; a starved reading is refused, a quiet one passes, an unreadable one is
UNKNOWN and never green; the refusal names the numbers, the top containers
and both fixes; main.yml runs it with the size check's tags; red-status sees it.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "docker-pressure-status.py"
MAIN = REPO / "main.yml"
VAR = "docker_memory_pressure_max_full_avg60"
ESCAPE = "nos_allow_memory_pressure"

# 2026-10-12 08:20, the failed converge. avg300 is the measured number; avg10
# and avg60 were not written down and are set at or above it, as a starve
# still in progress reads.
STARVED = ("some avg10=62.10 avg60=58.40 avg300=51.02 total=9120334411\n"
           "full avg10=38.90 avg60=36.20 avg300=34.55 total=6011223344\n")
# 2026-10-12, the same VM idle after the failed run (read live, 0.28).
QUIET = ("some avg10=0.03 avg60=0.39 avg300=0.19 total=1203533\n"
         "full avg10=0.03 avg60=0.28 avg300=0.13 total=1009453\n")
TOP = [("gitlab", 3_400_000_000), ("authentik-server", 900_000_000),
       ("postgresql", 700_000_000), ("ollama-proxy", 400_000_000),
       ("grafana", 300_000_000), ("redis", 50_000_000)]


def _tool():
    spec = importlib.util.spec_from_file_location("_docker_pressure", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _main_tasks() -> list[dict]:
    out = []
    for play in yaml.safe_load(MAIN.read_text(encoding="utf-8")):
        for key in ("pre_tasks", "tasks", "post_tasks"):
            out.extend(play.get(key) or [])
    return out


def _mod(t: dict, name: str):
    return t.get(name, t.get(f"ansible.builtin.{name}"))


def test_the_parser_reads_the_full_line():
    psi = _tool().parse_psi(STARVED)
    assert psi["full"]["avg60"] == 36.20 and psi["full"]["avg300"] == 34.55


def test_the_failed_converges_reading_is_refused():
    assert _tool().decide(_tool().parse_psi(STARVED), 10.0) == "starved"


def test_a_quiet_vm_passes():
    assert _tool().decide(_tool().parse_psi(QUIET), 10.0) == "ok"


def test_an_unreadable_probe_is_unknown_never_green():
    t = _tool()
    for text in (None, "", "garbage", "some avg10=1 avg60=1 avg300=1 total=1\n"):
        assert t.decide(t.parse_psi(text), 10.0) == "unknown", repr(text)


def test_the_refusal_says_what_to_do():
    t = _tool()
    msg = t.message(t.parse_psi(STARVED), 10.0, TOP)
    assert "36.2" in msg and "34.55" in msg and "10" in msg, "the numbers"
    for name, _ in TOP[:5]:
        assert name in msg, f"top container {name} missing"
    assert "redis" not in msg, "only the top 5"
    assert "Memory" in msg and "install_" in msg, "both fixes"
    assert "ollama" in msg.lower(), (
        "raising the VM above ~14.5 GiB starves ollama on the host; the "
        "message must not say only 'add more memory'")
    assert ESCAPE in msg and VAR in msg


def test_the_reader_is_unknown_when_docker_does_not_answer(monkeypatch):
    t = _tool()
    monkeypatch.setattr(t, "read_psi", lambda *a, **k: None)
    monkeypatch.setattr(t, "top_containers", lambda *a, **k: [])
    report = t.collect(10.0)
    assert report["verdict"] == "unknown" and report["sources_missing"]
    assert t.summary(report) == []


def test_the_reader_reports_a_starved_vm_red(monkeypatch):
    t = _tool()
    monkeypatch.setattr(t, "read_psi", lambda *a, **k: STARVED)
    monkeypatch.setattr(t, "top_containers", lambda *a, **k: TOP)
    report = t.collect(10.0)
    assert not report["sources_missing"]
    lines = t.summary(report)
    assert len(lines) == 1 and "36.2" in lines[0] and "gitlab" in lines[0]


def test_red_status_reads_it():
    src = (REPO / "tools" / "red-status.py").read_text(encoding="utf-8")
    assert '_sibling("docker-pressure")' in src


def test_the_playbook_refuses_a_starved_vm_with_the_size_checks_tags():
    tasks = _main_tasks()
    refusal = next((t for t in tasks if _mod(t, "fail") and VAR in str(t)), None)
    assert refusal is not None, f"main.yml has no refusal keyed on {VAR}"
    assert ESCAPE in str(refusal.get("when")), "the refusal has no escape"
    size = next(t for t in tasks
                if _mod(t, "fail") and "docker_min_memory_gib" in str(t.get("when", "")))
    probe = next(t for t in tasks if "docker-pressure-status.py" in str(_mod(t, "command")))
    assert probe.get("failed_when") is False, "an unreadable probe must never block"
    warn = next((t for t in tasks if _mod(t, "debug") and "unknown" in str(t.get("when", ""))), None)
    assert warn is not None, "an unreadable probe must warn, not pass silently"
    for t in (refusal, probe, warn):
        assert set(t.get("tags") or []) == set(size.get("tags") or []), t.get("name")


def test_the_threshold_is_declared_once():
    text = (REPO / "default.config.yml").read_text(encoding="utf-8")
    hits = re.findall(rf"^{VAR}:\s*([\d.]+)", text, re.M)
    assert len(hits) == 1, f"{VAR} must be declared exactly once in default.config.yml"
    assert 0.3 < float(hits[0]) < 34.55, (
        "the threshold must pass the quiet VM (0.28) and refuse the failed "
        "converge (34.55)")
