"""A job reaches its model through a tier variable, never a literal tag.

MEASURED 2026-10-09 on a clean client machine: the vision loops refused with
"is qwen2.5vl:7b pulled and ollama armed?" — a tag the config never named
(`ollama_vision_model: ""`). The runtime spoke of a model the configuration did
not hold, so the operator was told to fix the wrong thing. The id lives in ONE
place, the `ollama_*_model` tier variable (wing.plist -> NOS_LOCAL_*_MODEL);
code that names a tag has a second copy that drifts from it.

Reads artifacts, not prose: agent `model:` URIs, every scheduled job's
command/args/env, and the string constants (AST, docstrings excluded) of every
Python file a pulse job executes. Comments and docstrings may cite a tag.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
#: An ollama tag: family, a colon, a size in billions — qwen3:14b, hermes3:8b.
TAG = re.compile(r"\b[a-z][\w.\-]*:[\w.\-]*\d+b\b")


def _catalog() -> list[dict]:
    spec = importlib.util.spec_from_file_location(
        "_disc_tags", REPO / "files/anatomy/scripts/discover-pulse-catalog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    jobs = []
    for path in mod._scan_sources(str(REPO)):
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        block = mod._loop_pulse_block(doc) if path.endswith(".loop.yml") else (doc.get("pulse") or {})
        jobs += [(Path(path).relative_to(REPO), j) for j in block.get("jobs") or []]
    return jobs


def _code_strings(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)}
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def test_agent_models_are_tier_uris():
    bad = []
    for path in sorted(REPO.glob("files/anatomy/agents/*/agent.yml")):
        model = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("model") or {}
        for key in ("primary", "fallback"):
            if TAG.search(str(model.get(key) or "")):
                bad.append(f"{path.relative_to(REPO)} model.{key}={model[key]}")
    assert not bad, "agent binds a literal tag, not a tier:\n  " + "\n  ".join(bad)


def test_no_job_declaration_names_a_tag():
    bad = [f"{src} {job.get('name')}: {m.group(0)}"
           for src, job in _catalog()
           for field in ("command", "args", "env")
           for m in [TAG.search(str(job.get(field) or ""))] if m]
    assert not bad, "a job declaration hardcodes a model tag:\n  " + "\n  ".join(bad)


def test_no_job_script_names_a_tag():
    scripts = {(REPO / str(job["command"]).replace("{{ playbook_dir }}/", ""))
               for _, job in _catalog() if str(job.get("command", "")).endswith(".py")}
    assert scripts, "no python job found — this gate is blind"
    bad = [f"{p.relative_to(REPO)}:{line}: {m.group(0)}"
           for p in sorted(scripts) if p.is_file()
           for line, text in _code_strings(p) for m in [TAG.search(text)] if m]
    assert not bad, ("a job script names a model tag — say the tier variable "
                     "(ollama_vision_model …) instead:\n  " + "\n  ".join(bad))
