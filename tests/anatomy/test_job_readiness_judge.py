"""One judge answers "can this job succeed here", and the runners ask it.

MEASURED 2026-10-09 on a clean client machine (full converge failed=0):
eight pulse jobs failed every night and could never succeed — no claude CLI,
no armed backend, no vision model. They were armed anyway. The ruling that
day: the models and runtimes a job needs reflect the configuration, and nOS
must know whether it makes sense to run a job at all.

Fixtures, not the live host: every case hands the judge a config and host
facts, so the verdict is the rule's and not this machine's.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _judge():
    spec = importlib.util.spec_from_file_location("_job_readiness", REPO / "tools/job_readiness.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_job_readiness"] = mod
    spec.loader.exec_module(mod)
    return mod


CFG = {"ollama_enabled": "true", "ollama_model": "qwen3:14b",
       "ollama_small_model": "hermes3:8b", "ollama_vision_model": "qwen2.5vl:7b",
       "minimax_enabled": "true", "minimax_model": "MiniMax-M2",
       "install_claude_cli_vendor": "false"}
HOST = {"claude": "/Users/x/.local/bin/claude",
        "ollama_models": {"qwen3:14b", "hermes3:8b", "qwen2.5vl:7b"}, "anthropic_key": False}


def _needs(job_id, cfg=None, host=None):
    j = _judge()
    return j.job_needs(j.catalog()[job_id], {**CFG, **(cfg or {})}, {**HOST, **(host or {})})


def test_ready_when_every_need_is_met():
    for jid in ("loop:vision-bench", "loop:pipeline-exercise", "invoice-vision:intake-sweep",
                "conductor:vulnerability-scan", "librarian:judge-lint-queue",
                "surveyor:surface-survey"):
        assert _needs(jid) == [], f"{jid} held although every need is met"


def test_claude_missing():
    got = _needs("conductor:vulnerability-scan", host={"claude": None})
    assert got == ["claude CLI missing (set install_claude_cli_vendor: true, or install it)"]
    assert not got[0].required, "vendor install off: a decision, not a host defect"
    got = _needs("conductor:vulnerability-scan", cfg={"install_claude_cli_vendor": "true"},
                 host={"claude": None})
    assert got[0].required, "vendor install on and still no claude: the converge failed"


def test_vision_model_unset():
    got = _needs("loop:vision-bench", cfg={"ollama_vision_model": ""})
    assert got == ["vision model not configured (ollama_vision_model is empty)"]
    assert not got[0].required


def test_vision_model_not_pulled():
    got = _needs("loop:pipeline-exercise", host={"ollama_models": {"qwen3:14b", "hermes3:8b"}})
    assert got == ["model qwen2.5vl:7b not pulled"]
    assert got[0].required, "a configured model the host lacks fails the verify play"


def test_ollama_disabled():
    got = _needs("loop:vision-bench", cfg={"ollama_enabled": "false", "ollama_vision_model": ""})
    assert "ollama disabled (set ollama_enabled: true)" in got
    assert "vision model not configured (ollama_vision_model is empty)" in got


def test_an_agent_job_needs_its_armed_backend():
    got = _needs("librarian:judge-lint-queue", cfg={"minimax_enabled": "false"})
    assert len(got) == 1 and got[0].startswith("minimax backend not armed"), got
    assert _needs("librarian:judge-lint-queue", cfg={"minimax_enabled": "false"}) == \
        _needs("surveyor:surface-survey", cfg={"minimax_enabled": "false"}), (
        "one missing backend must read as ONE need, whichever agent hits it")


def test_the_client_estate_reads_as_three_needs():
    """Today's client config: no claude, minimax off, vision model empty."""
    j = _judge()
    cfg = {**CFG, "minimax_enabled": "false", "ollama_vision_model": ""}
    rows = j.table(cfg, {**HOST, "claude": None})
    groups = j.grouped(rows)
    assert set(groups) >= {
        "claude CLI missing (set install_claude_cli_vendor: true, or install it)",
        "vision model not configured (ollama_vision_model is empty)",
    } and any(n.startswith("minimax backend not armed") for n in groups), groups


def test_the_gate_holds_with_its_own_exit_code(capsys):
    j = _judge()
    rc = j.hold("loop:vision-bench", cfg={**CFG, "ollama_vision_model": ""}, host=HOST)
    assert rc == j.HOLD_EXIT == 78
    assert "HELD: vision model not configured" in capsys.readouterr().out, (
        "the HELD line must be on STDOUT — Pulse records only stdout")
    assert j.hold("loop:vision-bench", cfg=CFG, host=HOST) == 0


def test_every_scheduled_job_can_be_judged():
    j = _judge()
    rows = j.table(CFG, HOST)
    assert len(rows) > 20, "the judge sees too few jobs — it is blind"
    assert not [r for r in rows if any("unknown need" in n for n in r["needs"])]


def test_the_runners_ask_the_judge_before_they_spend():
    run_agent = (REPO / "tools/run-agent.sh").read_text(encoding="utf-8")
    assert run_agent.find("job_readiness.py") < run_agent.find("php bin/run-agent.php"), (
        "run-agent.sh must ask the judge before it opens a session")
    scan = (REPO / "files/vuln-scan/scan-runner.sh").read_text(encoding="utf-8")
    assert "job_readiness.py" in scan
    for script, job in (("tools/loops/vision-bench.py", "loop:vision-bench"),
                        ("tools/loops/pipeline-exercise.py", "loop:pipeline-exercise"),
                        ("tools/invoice-vision-intake.py", "invoice-vision:intake-sweep")):
        assert f'hold("{job}")' in (REPO / script).read_text(encoding="utf-8"), (
            f"{script} does not gate on its own job id")
