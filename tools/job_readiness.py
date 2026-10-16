#!/usr/bin/env python3
"""Can this job succeed here? One judge, asked before a job runs and by the readers.

MEASURED 2026-10-09 on a clean client machine (first greenfield deploy, full
converge failed=0): eight pulse jobs failed every night and could never succeed.
No claude CLI for the vulnerability scan, no armed backend for the librarian and
surveyor, no vision model for the invoice loops. Each was armed anyway, so
red-status listed eight failures where there were three missing needs, and the
loops blamed a model tag the config never named.

A job's needs come from what it runs: `run-agent.sh --agent=X` needs agent X's
backend (agent.yml model + state/habitat/llm-backends.yml, the BindingResolver
rules), a claude spawner needs the claude CLI, and a job may declare
`needs: [agent:<name>, claude-cli]` for what its command does not show. Inputs
are the resolved config (tools/nos_identity) and two host facts: which claude
resolves, and what `ollama list` holds.

    tools/job_readiness.py --job loop:vision-bench   # gate: exit 78 + HELD lines
    tools/job_readiness.py --agent librarian          # gate, for run-agent.sh
    tools/job_readiness.py [--json]                   # the table, exit 0
    tools/job_readiness.py --verify                   # exit 1 only on a need the
                                                      # config REQUIRES and the host lacks

HOLD_EXIT (78, sysexits EX_CONFIG) is the held run's code end to end; red-status
groups held runs by their `HELD:` line. The HELD lines go to STDOUT because
Pulse records only stdout in pulse_runs.stdout_tail.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity  # noqa: E402

#: A held run's exit code. Distinct from PAUSED_EXIT (3) and from every
#: findings code a job declares; mirrored in tools/red-status.py.
HOLD_EXIT = 78
BACKENDS = REPO / "state/habitat/llm-backends.yml"
PLIST = REPO / "roles/pazny.wing/templates/wing.plist.j2"
#: Commands that spawn the claude CLI themselves.
CLAUDE_SPAWNERS = {"scan-runner.sh", "pulse-run-agent.sh"}
CLAUDE_MISSING = "claude CLI missing (set install_claude_cli_vendor: true, or install it)"


class Need(str):
    """A missing need in operator words. `required`: the config asks for it and
    the host lacks it — the only kind the verify play fails on."""

    required: bool = False
    warn: bool = False      # said, never held (a model under llm_cell_recommended_params_b)

    def __new__(cls, text: str, required: bool = False, warn: bool = False):
        obj = super().__new__(cls, text)
        obj.required, obj.warn = required, warn
        return obj


def _backends() -> dict:
    return yaml.safe_load(BACKENDS.read_text(encoding="utf-8"))["backends"]


def _env_vars() -> dict[str, str]:
    """wing.plist env name -> the config variable it renders (NOS_LOCAL_MODEL -> ollama_model)."""
    return dict(re.findall(r"<key>(\w+)</key>\s*<string>\{\{\s*(\w+)",
                           PLIST.read_text(encoding="utf-8")))


def resolved_config() -> dict:
    """The values the judge reads, through every layer (config.yml wins), Jinja defaults rendered."""
    names = {"install_claude_cli_vendor", "llm_cell_min_params_b", "llm_cell_recommended_params_b", *_env_vars().values()}
    names |= {row["enabled_flag"] for row in _backends().values() if row.get("enabled_flag")}
    return {k: "" if v is None else v for k, v in nos_identity.resolved(names).items()}


def host_facts() -> dict:
    """Which claude resolves (Pulse's PATH plus the vendor's ~/.local/bin) and
    what `ollama list` holds — None when ollama does not answer."""
    path = os.pathsep.join([os.environ.get("PATH", ""), str(Path.home() / ".local/bin"),
                            "/opt/homebrew/bin", "/usr/local/bin"])
    claude = shutil.which(os.environ.get("NOS_CLAUDE_BIN") or "claude", path=path)
    models = None
    ollama = shutil.which("ollama", path=path)
    if ollama:
        try:
            out = subprocess.run([ollama, "list"], capture_output=True, text=True, timeout=20)
            if out.returncode == 0:
                models = {ln.split()[0] for ln in out.stdout.splitlines()[1:] if ln.strip()}
        except (OSError, subprocess.TimeoutExpired):
            models = None
    return {"claude": claude, "ollama_models": models,
            "anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY"))}


def _on(value) -> bool:
    return str(value).strip().lower() in ("true", "yes", "1")


def _pulled(model: str, have: set[str]) -> bool:
    return model in have or (":" not in model and f"{model}:latest" in have)


def _claude(cfg: dict, host: dict) -> list[Need]:
    if host.get("claude"):
        return []
    return [Need(CLAUDE_MISSING, required=_on(cfg.get("install_claude_cli_vendor")))]


def agent_needs(name: str, cfg: dict, host: dict) -> list[Need]:
    """What agent `name` lacks to open a session, by BindingResolver's rules."""
    path = REPO / "files/anatomy/agents" / name / "agent.yml"
    if not path.is_file():
        return []  # ponytail: an unknown agent is run-agent.php's refusal, not a need
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    model, gdpr = doc.get("model") or {}, doc.get("gdpr") or {}
    primary, declared = str(model.get("primary") or ""), model.get("backend")
    provider = primary.split("-", 1)[0]
    chosen = str(cfg.get("agents_backend") or "").strip()
    rebound = bool(chosen) and chosen != declared
    if rebound:
        refused = _host_choice_refusal(name, doc, chosen)
        if refused:
            return [Need(refused)]
        declared = chosen
    if declared:
        row = _backends().get(declared) or {}
        flag = row.get("enabled_flag") or ""
        m = re.search(r"\b(haiku|sonnet|opus|vision)\b", primary.split("-", 1)[-1])
        tier = m.group(1) if m else ""
        var = _env_vars().get((row.get("model_env") or {}).get(tier) or "", "")
        model_id = str(cfg.get(var, "")) if var else "set"
        if row.get("local"):
            # A local backend never degrades to the default: report every gap.
            needs = []
            if not _on(cfg.get(flag)):
                needs.append(Need(f"{declared} disabled (set {flag}: true)"))
            if var and not model_id:
                needs.append(Need(f"{tier} model not configured ({var} is empty)"))
            if needs or declared != "ollama":
                return needs
            size = _too_small(model_id, cfg) if rebound else []
            if [n for n in size if not n.warn]:
                return size
            have = host.get("ollama_models")
            if have is None:
                return [Need("ollama not answering (ollama list failed)", required=True)]
            return size + ([] if _pulled(model_id, have) else [Need(f"model {model_id} not pulled", required=True)])
        if _on(cfg.get(flag)):
            return [] if model_id else [Need(f"{declared} backend armed but {var} is empty")]
        eu_only = gdpr.get("transfers_outside_eu") is False and bool(gdpr.get("processors"))
        if eu_only or rebound:
            return [Need(f"{declared} backend not armed (set {flag}: true)")]
        if provider == "anthropic" and not host.get("anthropic_key"):
            return [Need(f"{declared} backend not armed — set {flag}: true and {var} "
                         "(unbound, anthropic-* needs an ANTHROPIC_API_KEY nOS never sets)")]
    if provider == "claude":
        return _claude(cfg, host)
    if provider == "anthropic" and not declared and not host.get("anthropic_key"):
        return [Need(f"{primary} needs ANTHROPIC_API_KEY or a model.backend")]
    return []


def _host_choice_refusal(name: str, doc: dict, chosen: str) -> str:
    """BindingResolver::decideHostChoice's refusals: agents_backend never rebinds an agent silently."""
    why = f"agent '{name}' cannot run on this host's agents_backend '{chosen}'"
    model, gdpr = doc.get("model") or {}, doc.get("gdpr") or {}
    primary = str(model.get("primary") or "")
    row = _backends().get(chosen)
    if primary.split("-", 1)[0] == "claude":
        return f"{why}: it runs on the claude CLI, which no registry row serves"
    if not isinstance(row, dict) or row.get("default"):
        return f"{why}: '{chosen}' is not a bindable row of {BACKENDS.relative_to(REPO)}"
    if str((doc.get("metadata") or {}).get("runner_status") or "").lower() == "deferred":
        return f"{why}: it is runner_status=deferred"
    match = str(row.get("processor_match") or "")
    if not match or not any(match in str((p or {}).get("name") or "") for p in gdpr.get("processors") or []):
        return f"{why}: its gdpr.processors never names '{match}'"
    if gdpr.get("transfers_outside_eu") is False and not (row.get("residency") or {}).get("eu"):
        return f"{why}: its record says transfers_outside_eu: false and '{chosen}' is not EU-resident"
    m = re.search(r"\b(haiku|sonnet|opus|vision)\b", primary.split("-", 1)[-1])
    if not m or not (row.get("model_env") or {}).get(m.group(1)):
        return f"{why}: its tier has no model on '{chosen}'"
    return ""


def _too_small(model_id: str, cfg: dict) -> list[Need]:
    """The size floors (tools/nos_cell_binding.py size_floor) for an agent agents_backend rebound:
    under llm_cell_min_params_b holds, under llm_cell_recommended_params_b only warns."""
    from nos_cell_binding import size_floor
    floor = float(cfg.get("llm_cell_min_params_b") or 3)
    refusal, warning = size_floor(model_id, floor, float(cfg.get("llm_cell_recommended_params_b") or floor))
    if refusal:
        return [Need(f"{refusal}, the floor agents_backend asks for")]
    return [Need(warning, warn=True)] if warning else []


def job_needs(job: dict, cfg: dict, host: dict) -> list[Need]:
    declared = [str(n) for n in job.get("needs") or []]
    args = [str(a) for a in job.get("args") or []]
    base = Path(str(job.get("command", ""))).name
    if base == "run-agent.sh":
        declared += [f"agent:{a.split('=', 1)[1]}" for a in args if a.startswith("--agent=")]
    if base in CLAUDE_SPAWNERS:
        declared.append("claude-cli")
    out: list[Need] = []
    for need in dict.fromkeys(declared):
        found = (_claude(cfg, host) if need == "claude-cli"
                 else agent_needs(need.split(":", 1)[1], cfg, host) if need.startswith("agent:")
                 else [Need(f"unknown need {need!r}")])
        out += [n for n in found if n not in out]
    return out


def catalog() -> dict[str, dict]:
    """job id -> job block, from the same sources the Pulse catalog reads."""
    spec = importlib.util.spec_from_file_location(
        "_disc_ready", REPO / "files/anatomy/scripts/discover-pulse-catalog.py")
    disc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(disc)
    out = {}
    for path in disc._scan_sources(str(REPO)):
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        loop = path.endswith(".loop.yml")
        block = disc._loop_pulse_block(doc) if loop else (doc.get("pulse") or {})
        owner = "loop" if loop else re.sub(r"-base$", "", str(doc.get("name") or Path(path).parent.name))
        for job in block.get("jobs") or []:
            if loop:
                job = {**job, "needs": (doc.get("pulse") or {}).get("needs") or []}
            out[f"{owner}:{job['name']}"] = job
    return out


def table(cfg: dict | None = None, host: dict | None = None) -> list[dict]:
    cfg = resolved_config() if cfg is None else cfg
    host = host_facts() if host is None else host
    return [{"job": jid, "needs": [n for n in needs if not n.warn], "required": [n for n in needs if n.required],
             "warnings": [n for n in needs if n.warn]}
            for jid, job in sorted(catalog().items()) if not job.get("paused")
            for needs in [job_needs(job, cfg, host)]]


def hold(job_id: str | None = None, agents: tuple[str, ...] = (),
         cfg: dict | None = None, host: dict | None = None) -> int:
    """The fire-time gate: print one HELD line per need, return HOLD_EXIT, or 0."""
    cfg = resolved_config() if cfg is None else cfg
    host = host_facts() if host is None else host
    job = dict(catalog().get(job_id) or {}) if job_id else {}
    job["needs"] = [*(job.get("needs") or []), *(f"agent:{a}" for a in agents)]
    needs = job_needs(job, cfg, host)
    for need in needs:
        print(f"{'WARN' if need.warn else 'HELD'}: {need}", flush=True)
    return HOLD_EXIT if [n for n in needs if not n.warn] else 0


def grouped(rows: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in rows:
        for need in row["needs"]:
            out.setdefault(need, []).append(row["job"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--job", help="gate this pulse job id (exit 78 when held)")
    ap.add_argument("--agent", action="append", default=[], help="gate this agent")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verify", action="store_true",
                    help="exit 1 on a need the config requires and the host lacks")
    args = ap.parse_args()
    if args.job or args.agent:
        return hold(args.job, tuple(args.agent))
    rows = table()
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    ready = [r["job"] for r in rows if not r["needs"]]
    print(f"{len(ready)} job(s) ready")
    required = {n for r in rows for n in r["required"]}
    for need, jobs in grouped(rows).items():
        mark = "MISSING" if need in required else "held"
        print(f"  {mark}: {len(jobs)} job(s) — {need}: {', '.join(jobs)}")
    for warn in sorted({w for r in rows for w in r["warnings"]}):
        print(f"  warn: {warn}")
    return 1 if args.verify and required else 0


if __name__ == "__main__":
    raise SystemExit(main())
