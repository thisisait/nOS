#!/usr/bin/env python3
"""Would this cell get a local model big enough to run it? Refuse before a converge builds anything.

decide() is files/anatomy/thalamus/thalamus/src/binding.rs ported line for line (same two files,
same gates, same order). Both run the cases in files/anatomy/thalamus/thalamus/tests/binding-cases.yml,
so a gate added to one and not the other goes red (tests/anatomy/test_llm_cell_requirement.py).

Usage (env = the binding env the service renders, e.g. pazny.thalamus thalamus_binding_env):
    tools/nos_cell_binding.py --service install_thalamus --cell iris --min-params-b 3 [--warn-below-b 8] [--repo DIR]
Exit 0: no requirement or it is met (a `WARN:` line when under --warn-below-b). Exit 2: refused;
the reason and the two fixes on stdout. size_floor() is binding.rs size_floor (binding-cases.yml sizes:).
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
              "NOS_LOCAL_VISION_MODEL": "vlm_model"}


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


def chosen_backend(agent, env) -> tuple[str, str]:
    """binding.rs: a host's NOS_CELL_BACKEND, only a row model.backends_allowed lists (ruling 2026-10-14)."""
    chosen = (env("NOS_CELL_BACKEND") or "").strip()
    if not chosen:
        return "", ""
    allowed = [b for b in (_at(agent, "model", "backends_allowed") or []) if isinstance(b, str)]
    if chosen not in allowed:
        listed = ", ".join(allowed) or _text(agent, "model", "backend")
        return chosen, f"agent '{_text(agent, 'name')}' may bind only {listed}; this host chose '{chosen}'"
    return chosen, ""


def decide(agent_yml: str, register_yml: str, env) -> Decision:
    """binding.rs decide(): Default / Disarmed / Bound, or refused with the same reason."""
    agent = yaml.safe_load(agent_yml) or {}
    register = yaml.safe_load(register_yml) if register_yml.strip() else None
    name, uri = _text(agent, "name"), _text(agent, "model", "primary")
    declared = _at(agent, "model", "backend")
    if not isinstance(declared, str):
        return Decision("default")
    chosen, why = chosen_backend(agent, env)
    if why:
        return Decision("refused", chosen, why=why)
    declared = chosen or declared
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

    # Gate 7 (key half): a key, unless the row is local and names none. The env answers nos:<var>.
    secret = _text(spec, "auth_secret")
    token = (env(secret) or "") if secret else ""
    if not token and (spec.get("local") is not True or secret):
        var = secret.removeprefix("nos:")
        return Decision("refused", declared, model_env, model_id, why=f"backend '{declared}' is armed but its auth_secret '{secret}' resolves to nothing: set {var} in credentials.yml and converge")
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


def size_floor(model: str, min_b: float, warn_b: float) -> tuple[str, str]:
    """(refusal, warning), "" when it does not apply: below min_b or unknown refuses, below warn_b warns."""
    size = params_b(model)
    if size is None:
        return f"the size of '{model}' is UNKNOWN (no NNb in its tag), so it cannot be shown to be at least {min_b:g}B", ""
    if size < min_b:
        return f"'{model}' has {size:g}B parameters, below the {min_b:g}B minimum (llm_cell_min_params_b)", ""
    if size < warn_b:
        return "", f"'{model}' has {size:g}B parameters, below the {warn_b:g}B recommended (llm_cell_recommended_params_b): it runs, badly"
    return "", ""


def _local_binding(repo: Path, cell: str, env) -> tuple[Decision, str, dict] | None:
    """decide() for a cell whose row is local, with that row; None when cloud-bound (or the default)."""
    agent_path = repo / "files/anatomy/agents" / cell / "agent.yml"
    agent_yml, register_yml = agent_path.read_text(), (repo / REGISTER).read_text()
    register = yaml.safe_load(register_yml) or {}
    agent = yaml.safe_load(agent_yml)
    declared = chosen_backend(agent, env)[0] or _at(agent, "model", "backend")
    spec = _at(register, "backends", declared) if isinstance(declared, str) else None
    if not isinstance(spec, dict) or spec.get("local") is not True:
        return None
    return decide(agent_yml, register_yml, env), declared, spec


def warning(repo: Path, cell: str, env, warn_b: float) -> str:
    """The WARN line for a bound local model under warn_b; "" otherwise."""
    got = _local_binding(repo, cell, env)
    if not got or got[0].kind != "bound":
        return ""
    why = size_floor(got[0].model_id, 0, warn_b)[1]
    return f"WARN: cell '{cell}' binds {why}" if why else ""


def requirement(repo: Path, service: str, cell: str, env, min_b: float) -> str | None:
    """None when the cell is cloud-bound or gets a big enough local model; else the refusal text."""
    chosen = (env("NOS_CELL_BACKEND") or "").strip()
    row = _at(yaml.safe_load((repo / REGISTER).read_text()), "backends", chosen) if chosen else None
    posture = (env("NOS_GDPR_POSTURE") or "standard").strip()
    if isinstance(row, dict) and _at(row, "residency", "eu") is not True and posture != "none":
        return (f"Refusing {service}: iris_backend '{chosen}' is not EU-resident and gdpr_posture is "
                f"'{posture}'. A non-EU row serves cell '{cell}' only under gdpr_posture: none.\n"
                f"Fix: choose an EU row (iris_backend: ollama, or \"\" for the declared one).")
    got = _local_binding(repo, cell, env)
    if got is None:
        return None                      # cloud (or the default): no local model needed
    d, declared, spec = got
    too_small = size_floor(d.model_id, min_b, 0)[0] if d.kind == "bound" else ""
    if d.kind == "bound" and not too_small:
        return None
    if declared not in (env("NOS_ARMED_BACKENDS") or "").split():
        why = f"{declared} is not enabled (ollama_enabled and install_ollama must both be true)"
    elif d.kind != "bound":
        why = f"the binding refuses it: {d.why}"
    else:
        why = too_small
    sizes = spec.get("sizes_b") or {}
    example = next((sizes[k] for k in sorted(sizes) if k >= min_b), f"a {min_b:g}b model")
    var = CONFIG_VAR.get(d.model_env, d.model_env or "the model var")
    rel = Path("files/anatomy/agents") / cell / "agent.yml"
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
    ap.add_argument("--warn-below-b", type=float, default=0, help="WARN (exit 0) under this size")
    ap.add_argument("--repo", type=Path, default=REPO)
    a = ap.parse_args()
    refusal = requirement(a.repo, a.service, a.cell, os.environ.get, a.min_params_b)
    print(refusal or warning(a.repo, a.cell, os.environ.get, a.warn_below_b)
          or f"{a.service}: cell '{a.cell}' needs no local model, or gets one of at least {a.min_params_b:g}B")
    return 2 if refusal else 0


if __name__ == "__main__":
    sys.exit(main())
