"""Every detector is registered in state/immune/indicators.yml, contract filled.

WHY. ssot/doctrine/immune-system.md §2: a detector that cannot fill the indicator
contract is not an indicator yet. Heartbeats and apoptosis read this registry,
so a reader or security patrol missing from it would go unwatched.

HOW. Enumerate tools/*-status.py and every plugin or agent-profile Pulse job
with `category: security`; each must be an `indicators` entry (or a reasoned
`not_indicators` / `not_indicator_jobs` line). The file validates against the schema next
to it, and every entry's `source` exists.
"""

from __future__ import annotations

import json
import pathlib

import jsonschema
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
REGISTRY = REPO / "state/immune/indicators.yml"
SCHEMA = REPO / "state/immune/indicators.schema.json"


def _registry() -> dict:
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))


def _security_jobs() -> set[str]:
    jobs = set()
    for path in sorted(REPO.glob("files/anatomy/plugins/*/plugin.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        plugin = str(doc.get("name") or path.parent.name).removesuffix("-base")
        for job in ((doc.get("pulse") or {}).get("jobs") or []):
            if job.get("category") == "security":
                jobs.add(f"{plugin}:{job['name']}")
    # Agent profiles declare Pulse jobs too; conductor's three security jobs went unseen.
    for path in sorted(REPO.glob("files/anatomy/agents/*/agent.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        agent = str(doc.get("name") or path.parent.name)
        for job in ((doc.get("pulse") or {}).get("jobs") or []):
            if job.get("category") == "security":
                jobs.add(f"{agent}:{job['name']}")
    return jobs


def test_registry_matches_schema():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = [f"{'/'.join(map(str, e.path))}: {e.message}"
              for e in jsonschema.Draft202012Validator(schema).iter_errors(_registry())]
    assert not errors, "state/immune/indicators.yml breaks its schema:\n" + "\n".join(errors)


def test_every_status_reader_is_accounted_for():
    reg = _registry()
    known = {pathlib.Path(v["source"]).name for v in reg["indicators"].values()} | set(reg["not_indicators"])
    missing = sorted(p.name for p in (REPO / "tools").glob("*-status.py") if p.name not in known)
    assert not missing, ("readers with no entry in state/immune/indicators.yml — register the "
                         "contract under `indicators`, or say why not under `not_indicators`: "
                         + ", ".join(missing))


def test_every_security_patrol_is_registered():
    reg = _registry()
    missing = sorted(_security_jobs() - set(reg["indicators"]) - set(reg.get("not_indicator_jobs") or {}))
    assert not missing, ("Pulse jobs with category security and no indicators entry: "
                         + ", ".join(missing))


def test_every_entry_names_a_source_that_exists():
    reg = _registry()
    gone = [k for k, v in reg["indicators"].items() if not (REPO / v["source"]).exists()]
    gone += [k for k in reg["not_indicators"] if not (REPO / "tools" / k).exists()]
    assert not gone, "registry entries whose source is gone: " + ", ".join(sorted(gone))
