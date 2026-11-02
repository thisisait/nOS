"""Wing ingests service-registry.json only after a render of it in the same task list.

MEASURED 2026-11-02 on a Linux host re-tenanted box.dev.local -> mini.local: the
converge ran Wing's ingest (pazny.wing post.yml, from stack-up) at 22:27:40 and
rendered the registry (tasks/service-registry.yml, near the end of main.yml) at
22:31:27. Wing kept every url on the old tenant, the hub probed hosts that no
longer resolve, and six services read down while they answered.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
INGEST = "bin/ingest-registry.php"
RENDER = "service-registry.json.j2"


def _flat(tasks: list) -> list[dict]:
    out = []
    for t in tasks or []:
        if isinstance(t, dict):
            out += [t] + _flat(t.get("block")) + _flat(t.get("rescue")) + _flat(t.get("always"))
    return out


def _task_lists() -> dict[str, list[dict]]:
    out = {}
    for root in ("roles", "tasks"):
        for p in (REPO / root).rglob("*.yml"):
            if "/tasks/" in f"/{p.relative_to(REPO)}" or root == "tasks":
                doc = yaml.safe_load(p.read_text(encoding="utf-8"))
                if isinstance(doc, list):
                    out[str(p.relative_to(REPO))] = _flat(doc)
    return out


def _body(t: dict) -> str:
    return json.dumps({k: v for k, v in t.items() if k not in ("name", "block", "rescue", "always")})


def test_every_ingest_follows_a_render() -> None:
    lists = _task_lists()
    ingesting = {f: ts for f, ts in lists.items() if any(INGEST in _body(t) for t in ts)}
    bad = []
    for f, ts in ingesting.items():
        rendered = False
        for t in ts:
            rendered = rendered or RENDER in _body(t)
            if INGEST in _body(t) and not rendered:
                bad.append(f)
    assert not bad, f"{bad} run {INGEST} before rendering the registry: they ingest the last run's file"
    assert "tasks/service-registry.yml" in ingesting, "the registry render no longer hands Wing its result"
