#!/usr/bin/env python3
"""Which tissues does the estate declare, and does each one hold together?

    tools/tissue-status.py              every tissue: its members, OK or REFUSED
    tools/tissue-status.py backoffice   one tissue, with the Article 30 it inherits
    tools/tissue-status.py --json

A tissue (docs/doctrine/tissues.md, PROPOSED) is state/tissues/<name>.tissue.yml:
a list of ids that already exist elsewhere. This loader validates it against
state/genome/tissue.schema.json and resolves every id against its own source;
one dangling reference refuses the whole tissue. tools/anatomy-graph-gen.py
imports load() and dies on a refusal; this CLI is a READER and exits 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
TISSUES = REPO / "state" / "tissues"
SCHEMA = REPO / "state" / "genome" / "tissue.schema.json"
APP_SCHEMA = REPO / "state" / "schema" / "app.schema.json"

sys.path.insert(0, str(REPO / "files" / "anatomy"))
from module_utils.nos_app_parser import GDPR_LEGAL_BASES, REQUIRED_GDPR  # noqa: E402


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _schema_errors(doc: dict) -> list[str]:
    import jsonschema
    from referencing import Registry, Resource
    app = json.loads(APP_SCHEMA.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    reg = Registry().with_resource(app["$id"], Resource.from_contents(app))
    v = jsonschema.Draft7Validator(schema, registry=reg)
    return [f"schema: /{'/'.join(map(str, e.path))} {e.message}" for e in v.iter_errors(doc)]


def _manifest_services() -> dict[str, dict]:
    return {s["id"]: s for s in _yaml(REPO / "state" / "manifest.yml").get("services") or []}


def _roadmap_slugs() -> set[str]:
    return {r.get("slug") for r in yaml.safe_load(
        (REPO / "state" / "roadmap" / "index.yml").read_text(encoding="utf-8")) or []}


def _plugin(owner: str) -> Path:
    return REPO / "files" / "anatomy" / "plugins" / f"{owner}-base" / "plugin.yml"


def resolve(doc: dict) -> tuple[list[str], dict[str, dict]]:
    """(dangling references, {processor label: its gdpr block}) for one tissue.
    The processors are every member that declares Article 30 for itself."""
    bad: list[str] = []
    gdpr: dict[str, dict] = {}
    for c in doc.get("cells") or []:
        p = REPO / "files" / "anatomy" / "agents" / c / "agent.yml"
        if p.is_file():
            gdpr[f"cell {c}"] = _yaml(p).get("gdpr")
        else:
            bad.append(f"cell {c}: no {p.relative_to(REPO)}")
    for s in doc.get("skills") or []:
        if not (REPO / "files" / "anatomy" / "skills" / s / "SKILL.md").is_file():
            bad.append(f"skill {s}: no files/anatomy/skills/{s}/SKILL.md")
    for t in doc.get("tables") or []:
        if not (REPO / "state" / "keap-tables" / f"{t}.table.yml").is_file():
            bad.append(f"table {t}: no state/keap-tables/{t}.table.yml")
    services = _manifest_services()
    for s in doc.get("services") or []:
        if s not in services:
            bad.append(f"service {s}: no state/manifest.yml row")
        elif not _plugin(s).is_file():
            bad.append(f"service {s}: no plugin {_plugin(s).relative_to(REPO)}")
        else:
            gdpr[f"service {s}"] = _yaml(_plugin(s)).get("gdpr")
    for r in doc.get("reflexes") or []:
        owner, job = r.split(":", 1)
        plug = _yaml(_plugin(owner)) if _plugin(owner).is_file() else {}
        if job not in {j.get("name") for j in (plug.get("pulse") or {}).get("jobs") or []}:
            bad.append(f"reflex {r}: no pulse job {job!r} in {owner}-base/plugin.yml")
        else:
            gdpr[f"reflex {r}"] = plug.get("gdpr")
    for i in doc.get("importers") or []:
        p = REPO / "state" / "digest-importers" / f"{i}.importer.yml"
        if p.is_file():
            gdpr[f"importer {i}"] = _yaml(p).get("gdpr")
        else:
            bad.append(f"importer {i}: no {p.relative_to(REPO)}")
    for s in doc.get("seeds") or []:
        if not (REPO / "state" / "fixtures" / f"{s}.seed.yml").is_file():
            bad.append(f"seed {s}: no state/fixtures/{s}.seed.yml")
    if doc.get("profile") and not (REPO / "profiles" / f"{doc['profile']}.yml").is_file():
        bad.append(f"profile {doc['profile']}: no profiles/{doc['profile']}.yml")
    slugs = _roadmap_slugs()
    for f in doc.get("acceptance") or []:
        for need in (REPO / "state" / "fixtures" / f"{f}.seed.yml",
                     REPO / "state" / "fixtures" / f / "expected.yml"):
            if not need.is_file():
                bad.append(f"acceptance {f}: no {need.relative_to(REPO)}")
        if f"fixture-{f}" not in slugs:
            bad.append(f"acceptance {f}: no roadmap row fixture-{f}")
    return bad, gdpr


def art30_gaps(gdpr: dict[str, dict]) -> list[str]:
    """Each processor's own block must be complete; the tissue adds none."""
    out = []
    for who, g in sorted(gdpr.items()):
        if not isinstance(g, dict):
            out.append(f"{who}: no gdpr block")
            continue
        out += [f"{who}: gdpr.{k} missing" for k in REQUIRED_GDPR if k not in g]
        if g.get("legal_basis") not in GDPR_LEGAL_BASES:
            out.append(f"{who}: gdpr.legal_basis {g.get('legal_basis')!r} is not an Art 6(1) basis")
    return out


def load(path: Path) -> dict:
    """One tissue: its document plus `refused` (every reason, empty when it holds)."""
    doc = _yaml(path)
    name = path.name.removesuffix(".tissue.yml")
    refused = _schema_errors(doc)
    if (doc.get("meta") or {}).get("name") != name:
        refused.append(f"meta.name {(doc.get('meta') or {}).get('name')!r} is not the file name {name!r}")
    bad, gdpr = resolve(doc) if not refused else ([], {})
    refused += bad + art30_gaps(gdpr)
    return {"name": name, "source": str(path.relative_to(REPO)), "doc": doc,
            "processors": sorted(gdpr), "refused": refused}


def load_all() -> list[dict]:
    return [load(p) for p in sorted(TISSUES.glob("*.tissue.yml"))]


def main() -> int:
    ap = argparse.ArgumentParser(description="the estate's tissues and whether each holds")
    ap.add_argument("name", nargs="?")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    try:
        tissues = [t for t in load_all() if args.name in (None, t["name"])]
    except (OSError, ValueError, ImportError, yaml.YAMLError) as exc:
        print(f"tissue: UNKNOWN — cannot read the tissue manifests ({exc})")
        return 0
    if args.json:
        print(json.dumps(tissues, indent=2, ensure_ascii=False))
        return 0
    if not tissues:
        print(f"tissue: none declared{' named ' + args.name if args.name else ''} under state/tissues/")
    for t in tissues:
        d = t["doc"]
        print(f"{t['name']}  {'REFUSED' if t['refused'] else 'OK'}  ({t['source']})")
        for key in ("cells", "skills", "tables", "services", "reflexes", "importers", "seeds",
                    "acceptance"):
            print(f"  {key:<11}{', '.join(d.get(key) or []) or '—'}")
        if args.name:
            print(f"  art. 30 inherited from: {', '.join(t['processors']) or '—'}")
        for why in t["refused"]:
            print(f"  refused: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
