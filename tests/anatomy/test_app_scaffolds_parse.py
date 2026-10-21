"""Anatomy gate — every part Iris's scaffold_app hands out parses under nOS's own app parser.

THE RISK (2026-10-21, iris-app-toolchain). scaffold_app gives the model infra and backend parts to
assemble into apps/<name>.yml. A part the parser refuses is a second, wrong definition of an app.

THE CHECK. Each runtime's infra part, and each runtime's infra + backend, filled with sample values the
way serve.rs fills them (text replace, then YAML), joined to a meta + gdpr, passes parse_app_file and the
EU-residency gate; every image is an official docker.io/library tag pinned to x.y.z.

CEILING. Parses the manifest; whether the container boots is the converge's and the app reader's.
"""

import copy
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files" / "anatomy"))
from module_utils import nos_app_parser  # noqa: E402

S = yaml.safe_load((REPO / "state" / "app-scaffolds.yml").read_text(encoding="utf-8"))
NAME = "my-notes"


def fill(text: str, runtime: str, port: int = 8123) -> dict:
    """serve.rs scaffold_app's fill, token for token."""
    r = S["runtimes"][runtime]
    for k, v in {"<name>": NAME, "<token>": NAME.upper().replace("-", "_"), "<port>": str(port),
                 "<cport>": str(r["port"]), "<image>": r["image"], "<health>": json.dumps(r["health"]),
                 "<command>": json.dumps(r.get("command"))}.items():
        text = text.replace(k, v)
    return yaml.safe_load(text)


def merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in b.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


BASE = {"meta": {"name": NAME, "version": "1.0.0", "summary": "A small notes app."},
        "gdpr": {"purpose": "Keeps the person's notes.", "legal_basis": "contract", "data_categories": ["notes"],
                 "data_subjects": ["employees"], "retention_days": 365, "processors": [], "transfers_outside_eu": False}}


def parsed(tmp_path: Path, manifest: dict) -> dict:
    f = tmp_path / f"{NAME}.yml"
    f.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    rec = nos_app_parser.parse_app_file(str(f))
    ok, bad = nos_app_parser.gate_eu_residency(rec)
    assert ok, bad
    return rec


@pytest.mark.parametrize("runtime", sorted(S["runtimes"]))
def test_infra_part_parses(tmp_path, runtime):
    rec = parsed(tmp_path, merge(BASE, fill(S["infra"], runtime)))
    svc = rec["compose"]["services"][NAME]
    # Operator 2026-10-21: exposed to Traefik over the network, no host port, no networks list (the runner's default).
    assert svc["expose"] == [str(S["runtimes"][runtime]["port"])] and "ports" not in svc, "no host port by default"
    assert "networks" not in svc and svc["mem_limit"] and svc["cpus"]


@pytest.mark.parametrize("runtime", sorted(r for r in S["runtimes"] if "command" in S["runtimes"][r]))
def test_infra_plus_backend_parses(tmp_path, runtime):
    m = merge(merge(BASE, fill(S["infra"], runtime)), fill(S["backend"], runtime))
    env = parsed(tmp_path, m)["compose"]["services"][NAME]["environment"]
    assert any("$SERVICE_FQDN_MY_NOTES" in e for e in env), env


def test_every_image_is_a_pinned_official_tag():
    for name, r in S["runtimes"].items():
        assert re.fullmatch(r"docker\.io/library/[a-z]+:\d+\.\d+\.\d+-(alpine|slim)", r["image"]), (name, r["image"])


def test_frontend_routes_a_table_editor_to_tables_app():
    f = S["frontend"]
    assert {x["path"] for x in f["files"]} == {"index.html", "app.js", "style.css"}
    assert any("TablesApp" in i for i in f["instead"]) and any("KEAP" in m for m in f["may_not_call"])
