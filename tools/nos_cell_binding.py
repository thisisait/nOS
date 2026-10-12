#!/usr/bin/env python3
"""Would this cell get a local model big enough to run it? Refuse before a converge builds anything.

decide() is files/anatomy/thalamus/thalamus/src/binding.rs ported line for line (same two files,
same gates, same order). Both run the cases in files/anatomy/thalamus/thalamus/tests/binding-cases.yml,
so a gate added to one and not the other goes red (tests/anatomy/test_llm_cell_requirement.py).

Usage (env = the binding env the service renders, e.g. pazny.thalamus thalamus_binding_env):
    tools/nos_cell_binding.py --service install_thalamus --cell iris --min-params-b 8 [--repo DIR]
Exit 0: no requirement or it is met. Exit 2: refused; the reason and the two fixes on stdout.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
REGISTER = "state/habitat/llm-backends.yml"
# The config var that fills each local model env (the thalamus plist and wing.plist render these).
CONFIG_VAR = {"NOS_LOCAL_MODEL": "ollama_model", "NOS_LOCAL_SMALL_MODEL": "ollama_small_model",
              "NOS_LOCAL_VISION_MODEL": "ollama_vision_model"}


@dataclass
class Decision:
    kind: str                 # default | disarmed | bound | refused
    backend: str = ""
    model_env: str = ""
    model_id: str = ""
    why: str = ""


def _at(v, *path):
    for k in path:
        v = v.get(k) if isinstance(v, dict) else None
    return v


def _text(v, *path) -> str:
    x = _at(v, *path)
    return x if isinstance(x, str) else ""


def decide(agent_yml: str, register_yml: str, env) -> Decision:
    """binding.rs decide(): Default / Disarmed / Bound, or refused with the same reason."""
    agent = yaml.safe_load(agent_yml) or {}
    register = yaml.safe_load(register_yml) if register_yml.strip() else None
    name, uri = _text(agent, "name"), _text(agent, "model", "primary")
    declared = _at(agent, "model", "backend")
    if not isinstance(declared, str):
        return Decision("default")
    spec = _at(register, "backends", declared)
    if spec is None:
        return Decision("refused", declared, why=f"agent '{name}' declares backend '{declared}', which {REGISTER} does not list")
    if spec.get("default") is True:
        return Decision("default", declared)

    provider, sep, tail = uri.partition("-")
    if not sep:
        provider, tail = "", uri[1:]
    speaks = {"claude": "anthropic", "anthropic": "anthropic", "openai": "openai", "openclaw": "openai"}.get(provider, "")
    protocol = spec.get("protocol") if isinstance(spec.get("protocol"), str) else "anthropic"
    if speaks != protocol:
        return Decision("refused", declared, why=f"agent '{name}': provider '{provider}' does not speak backend '{declared}'s wire protocol '{protocol}'")

    if _text(agent, "metadata", "runner_status").lower() == "deferred":
        return Decision("refused", declared, why=f"agent '{name}' is runner_status=deferred; refusing to bind it")

    processors = _at(agent, "gdpr", "processors") or []
    matcher = _text(spec, "processor_match")
    if not matcher or not any(matcher in _text(p, "name") for p in processors):
        return Decision("refused", declared, why=f"agent '{name}' routes to '{declared}' but its own gdpr.processors never names '{matcher}'")
    eu_only = _at(agent, "gdpr", "transfers_outside_eu") is False and bool(processors)
    if eu_only and _at(spec, "residency", "eu") is not True:
        return Decision("refused", declared, why=f"agent '{name}' declares transfers_outside_eu: false but routes to '{declared}', which is not EU-resident")

    words = re.split(r"[^A-Za-z0-9_]", tail)
    tier = next((w for w in words if w in ("haiku", "sonnet", "opus", "vision")), tail)
    model_env = _at(spec, "model_env", tier)
    if not isinstance(model_env, str):
        return Decision("refused", declared, why=f"agent '{name}' (tier '{tier}', from '{uri}') has no model mapping on backend '{declared}'")

    if declared not in (env("NOS_ARMED_BACKENDS") or "").split():
        if eu_only:
            return Decision("refused", declared, model_env, why=f"agent '{name}' declares transfers_outside_eu: false and its backend '{declared}' is not armed")
        return Decision("disarmed", declared, model_env)
    model_id = env(model_env) or ""
    if not model_id:
        return Decision("refused", declared, model_env, why=f"backend '{declared}' is armed but {model_env} is empty; refusing to send a blank model id")

    secret = _text(spec, "auth_secret")
    if spec.get("local") is not True or secret:
        return Decision("refused", declared, model_env, model_id, why=f"backend '{declared}' is armed but its auth_secret '{secret}' resolves to nothing here (the thalamus holds no vault)")
    return Decision("bound", declared, model_env, model_id)


_SIZE = re.compile(r"(?:^|[-_])(?:(\d+)x)?(\d+(?:\.\d+)?)([bm])(?=$|[-_])", re.I)


def params_b(model: str) -> float | None:
    """Parameters in billions from an ollama tag (qwen3:14b -> 14, mixtral:8x7b -> 56); None = unknown."""
    _, sep, tag = model.rpartition(":")
    m = _SIZE.search(tag) if sep else None
    if not m:
        return None
    n = float(m[2]) * (int(m[1]) if m[1] else 1)
    return n / 1000 if m[3].lower() == "m" else n


def requirement(repo: Path, service: str, cell: str, env, min_b: float) -> str | None:
    """None when the cell is cloud-bound or gets a big enough local model; else the refusal text."""
    agent_path = repo / "files/anatomy/agents" / cell / "agent.yml"
    agent_yml, register_yml = agent_path.read_text(), (repo / REGISTER).read_text()
    register = yaml.safe_load(register_yml) or {}
    declared = _at(yaml.safe_load(agent_yml), "model", "backend")
    spec = _at(register, "backends", declared) if isinstance(declared, str) else None
    if not isinstance(spec, dict) or spec.get("local") is not True:
        return None                      # cloud (or the default): no local model needed
    d = decide(agent_yml, register_yml, env)
    ok_size = params_b(d.model_id) if d.kind == "bound" else None
    if ok_size is not None and ok_size >= min_b:
        return None
    if declared not in (env("NOS_ARMED_BACKENDS") or "").split():
        why = f"{declared} is not enabled (ollama_enabled and install_ollama must both be true)"
    elif d.kind != "bound":
        why = f"the binding refuses it: {d.why}"
    elif ok_size is None:
        why = f"the size of '{d.model_id}' is UNKNOWN (no NNb in its tag), so it cannot be shown to be at least {min_b:g}B"
    else:
        why = f"'{d.model_id}' has {ok_size:g}B parameters, below the {min_b:g}B minimum (llm_cell_min_params_b)"
    sizes = spec.get("sizes_b") or {}
    example = next((sizes[k] for k in sorted(sizes) if k >= min_b), f"a {min_b:g}b model")
    var = CONFIG_VAR.get(d.model_env, d.model_env or "the model var")
    rel = agent_path.relative_to(repo)
    model = d.model_id or (env(d.model_env) if d.model_env else "") or "(none set)"
    return (f"Refusing {service}: it needs cell '{cell}', which is bound to the local backend '{declared}', "
            f"and the model it would bind is {model}"
            f"{f' ({d.model_env}, from {var})' if d.model_env else ''}.\n"
            f"Why: {why}.\n"
            f"Fix, either:\n"
            f"  1. enable ollama with a model of at least {min_b:g}B: ollama_enabled: true, install_ollama: true "
            f"and {var}: \"{example}\" in config.yml (ollama list must show it); or\n"
            f"  2. bind '{cell}' to a cloud backend: model.backend in {rel} names a row of {REGISTER} "
            f"without local: true, and the cell's gdpr block names that processor.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--service", required=True)
    ap.add_argument("--cell", required=True)
    ap.add_argument("--min-params-b", type=float, required=True)
    ap.add_argument("--repo", type=Path, default=REPO)
    a = ap.parse_args()
    refusal = requirement(a.repo, a.service, a.cell, os.environ.get, a.min_params_b)
    print(refusal or f"{a.service}: cell '{a.cell}' needs no local model, or gets one of at least {a.min_params_b:g}B")
    return 2 if refusal else 0


if __name__ == "__main__":
    sys.exit(main())
