"""A model the config names is a model the playbook pulls.

MEASURED 2026-10-09 on a clean client machine (first greenfield deploy, full
converge failed=0): `loop:vision-bench` and `loop:pipeline-exercise` were rc=2
every night — "is qwen2.5vl:7b pulled and ollama armed?". `ollama list` held
three models, none of them a tier the agents bind to. The config only NAMED
the ids ("the operator pulls it"); nothing pulled them, so a job ran against a
model that was never there.

This holds the shape: roles/pazny.ollama derives `ollama_pull_models` from the
tier variables, every tier env the ollama backend row binds (via wing.plist)
is in it, and the role pulls that list. Whether the pull SUCCEEDED is the
verify play's question (tools/job_readiness.py --verify), not this file's.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
DEFAULTS = REPO / "roles/pazny.ollama/defaults/main.yml"
TASKS = REPO / "roles/pazny.ollama/tasks/main.yml"
PLIST = REPO / "roles/pazny.wing/templates/wing.plist.j2"
BACKENDS = REPO / "state/habitat/llm-backends.yml"


def _pull_list(**cfg) -> list:
    raw = (yaml.safe_load(DEFAULTS.read_text(encoding="utf-8")) or {}).get("ollama_pull_models")
    assert isinstance(raw, str), "roles/pazny.ollama/defaults declares no ollama_pull_models"
    env = jinja2.Environment()
    env.filters["bool"] = lambda v: str(v).lower() in ("true", "yes", "1")
    return ast.literal_eval(env.from_string(raw).render(**cfg))


def test_every_configured_tier_model_is_pulled():
    got = _pull_list(ollama_enabled=True, ollama_model="qwen3:14b",
                     ollama_small_model="hermes3:8b", ollama_vision_model="qwen2.5vl:7b")
    assert sorted(got) == ["hermes3:8b", "qwen2.5vl:7b", "qwen3:14b"]


def test_an_empty_tier_is_not_pulled_and_duplicates_collapse():
    got = _pull_list(ollama_enabled=True, ollama_model="qwen3:14b",
                     ollama_small_model="qwen3:14b", ollama_vision_model="")
    assert got == ["qwen3:14b"]


def test_ollama_disabled_pulls_nothing():
    assert _pull_list(ollama_enabled=False, ollama_model="qwen3:14b",
                      ollama_small_model="hermes3:8b", ollama_vision_model="x:1") == []


def test_every_tier_the_ollama_backend_binds_is_in_the_pull_list():
    """A new tier env on the ollama row (a fifth tier) must join the pull list."""
    plist = PLIST.read_text(encoding="utf-8")
    env_to_var = dict(re.findall(r"<key>(\w+)</key>\s*<string>\{\{\s*(\w+)", plist))
    row = yaml.safe_load(BACKENDS.read_text(encoding="utf-8"))["backends"]["ollama"]
    raw = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))["ollama_pull_models"]
    for tier, env in (row.get("model_env") or {}).items():
        if env is None:
            continue
        var = env_to_var.get(env)
        assert var, f"tier {tier}: {env} has no config variable in wing.plist.j2"
        assert re.search(rf"\b{var}\b", raw), (
            f"tier {tier} binds {env} = {var}, which ollama_pull_models never pulls")


def test_the_role_pulls_the_list():
    tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
    pulls = [t for t in tasks if "ollama pull" in str(t.get("ansible.builtin.command", ""))
             and "ollama_pull_models" in str(t.get("loop", ""))]
    assert pulls, "roles/pazny.ollama has no task that pulls ollama_pull_models"
