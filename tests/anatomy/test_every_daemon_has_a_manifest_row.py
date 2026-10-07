"""Anatomy CI gate — every host daemon is bound to exactly one manifest row.

MEASURED 2026-10-05 (naming study): 11 of 19 `daemon:` nodes had no manifest
row, the openclaw row named a label no role renders (`eu.thisisait.nos.openclaw`;
the role starts `ai.openclaw.gateway`), wing and alloy rows had no
`launchd_label`, and `daemon:eu.thisisait.nos.ears` was the ears .app BUNDLE id,
harvested because its value merely looked like a label. Two representations of
one fact, no join between them. The join is `launchd_label` (+ `launchd_helpers`
for a row's second job); a daemon no service owns is RULED in
`daemons_without_row` (reflex or internal of its owner, or the heartbeat); a
host-native row with no launchd job says what it is in `host_process`.

I-12 (2026-10-07): one organ, one node. A row's labels sit on its service: node
as `launchd_labels` and get no daemon: node; a ruled reflex/internal gets none
either; the heartbeat keeps its node at level cross. Reads the graph, the
manifest and the role declarations; never the live host.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _graph() -> dict:
    return json.loads((REPO / "state/anatomy-graph.json").read_text(encoding="utf-8"))["nodes"]


def _manifest() -> dict:
    return yaml.safe_load((REPO / "state/manifest.yml").read_text(encoding="utf-8"))


def _daemons() -> set[str]:
    return {k.split(":", 1)[1] for k, v in _graph().items() if v.get("kind") == "daemon"}


def _owners() -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for row in _manifest()["services"]:
        for label in [row.get("launchd_label"), *(row.get("launchd_helpers") or [])]:
            if label:
                owners.setdefault(label, []).append(row["id"])
    return owners


def _rulings() -> dict[str, dict]:
    return _manifest().get("daemons_without_row") or {}


def _declared() -> set[str]:
    """Every label a role or template declares (the generator's own reader)."""
    spec = importlib.util.spec_from_file_location("_gen", REPO / "tools" / "anatomy-graph-gen.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    return gen.declared_launchd_labels()


def _carried() -> dict[str, list[str]]:
    """launchd label -> service nodes carrying it (`launchd_labels`, I-12)."""
    out: dict[str, list[str]] = {}
    for nid, n in _graph().items():
        for label in n.get("launchd_labels") or []:
            out.setdefault(label, []).append(nid)
    return out


def test_every_daemon_has_one_row_or_a_reason():
    owners, reasons = _owners(), _rulings()
    bad = []
    for label in sorted(_daemons()):
        rows = owners.get(label, [])
        if len(rows) > 1:
            bad.append(f"{label}: owned by {rows} — one daemon, one row")
        elif rows and label in reasons:
            bad.append(f"{label}: row {rows[0]} AND a daemons_without_row ruling — pick one")
        elif not rows and not str((reasons.get(label) or {}).get("reason") or "").strip():
            bad.append(f"{label}: no manifest row and no daemons_without_row ruling")
    assert not bad, "\n".join(bad)


def test_every_declared_label_is_a_row_or_ruled_and_vice_versa():
    """The two-way join, after the fold: every label a role declares is one
    row's or ruled; every row label is declared AND sits on that row's node."""
    declared, owners, rulings, carried = _declared(), _owners(), _rulings(), _carried()
    bad = [f"{label}: declared by a role, no manifest row and no daemons_without_row ruling"
           for label in sorted(declared - set(owners) - set(rulings))]
    bad += [f"{label}: row {rows} names it but no role renders it"
            for label, rows in owners.items() if label not in declared]
    bad += [f"{label}: daemons_without_row names it but no role renders it"
            for label in rulings if label not in declared]
    bad += [f"{label}: row {rows}, but graph node(s) {carried.get(label)} carry it"
            for label, rows in owners.items() if carried.get(label) != [f"service:{rows[0]}"]]
    bad += [f"{label}: on a service node {nodes} but owned by no row"
            for label, nodes in carried.items() if label not in owners]
    assert not bad, "\n".join(bad)


def test_a_ruled_job_is_no_organ_and_the_heartbeat_keeps_its_node():
    """`ruling` is a lexicon word at level cross or internal; `of` is a row or
    playbook-core; reflex/internal emit no node, heartbeat emits exactly one."""
    words = yaml.safe_load((REPO / "state/genome/lexicon.yml").read_text(encoding="utf-8"))["words"]
    rows = {r["id"] for r in _manifest()["services"]}
    daemons = _daemons()
    bad = []
    for label, r in _rulings().items():
        if words.get(r.get("ruling"), {}).get("level") not in ("cross", "internal"):
            bad.append(f"{label}: ruling {r.get('ruling')!r} is no cross/internal lexicon word")
        if r.get("of") not in rows | {"playbook-core"}:
            bad.append(f"{label}: of {r.get('of')!r} is neither a row nor playbook-core")
        if r.get("ruling") in ("reflex", "internal") and label in daemons:
            bad.append(f"{label}: ruled {r['ruling']} of {r.get('of')} yet still a daemon node")
        if r.get("ruling") == "heartbeat" and label not in daemons:
            bad.append(f"{label}: ruled heartbeat but has no daemon node")
    assert not bad, "\n".join(bad)


def test_a_host_native_row_names_its_daemon_or_what_it_is():
    bad = [row["id"] for row in _manifest()["services"]
           if row.get("stack") is None
           and not row.get("launchd_label") and not str(row.get("host_process") or "").strip()]
    assert not bad, f"stack: null rows with neither launchd_label nor host_process: {bad}"


def test_only_a_launchd_label_var_declares_a_daemon():
    """The ears bundle id became a daemon because its VALUE carried the
    eu.thisisait.nos. prefix. The declaration is the var name, not the shape."""
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity as ni  # noqa: E402

    text = "\n".join([*(p.read_text(encoding="utf-8") for p in REPO.glob("roles/*/defaults/main.yml")),
                      ni.default_config_text()])  # every default layer, not one file
    declared = set(re.findall(r'^\w+_launchd_label:\s*"([\w.\-]+)"', text, re.M))
    declared |= {p.name.removesuffix(".plist.j2") for p in REPO.glob("templates/eu.thisisait.nos.*.plist.j2")}
    stray = sorted(_daemons() - declared)
    assert not stray, f"daemon nodes not declared by a *_launchd_label var: {stray}"


def test_a_host_native_service_is_not_described_as_docker():
    bad = [nid for nid, n in _graph().items()
           if n.get("kind") == "service" and n.get("stack") is None
           and "Docker" in n.get("description", "")]
    assert not bad, f"host-native rows described as Docker services: {bad}"


def _body_plan() -> dict:
    return json.loads((REPO / "state/body-plan.json").read_text(encoding="utf-8"))


def test_the_body_plan_counts_each_organ_once():
    """MEASURED 2026-10-07 (I-12): the organ level held 73 rows + 18 daemon nodes
    + 7 face apps + the repo surfaces, so wing, bone, pulse and cortex were each
    two organs and a face app was one. An organ is one row (body-plan.md §5);
    the only other organ-level node is a declared repo surface."""
    plan = _body_plan()
    organs = [nid for nid, n in plan["nodes"].items() if n["level"] == "organ"]
    repos = [nid for nid in organs if nid.startswith("repo:")]
    rows = len(_manifest()["services"])
    extra = sorted(nid for nid in organs if not nid.startswith(("service:", "repo:")))
    assert len(organs) == rows + len(repos) and not extra, (
        f"organ level holds {len(organs)} nodes, manifest {rows} rows + {len(repos)} repo "
        f"surfaces = {rows + len(repos)}; nodes that are not a row or a repo surface: {extra}")


def test_no_organ_node_carries_a_rows_launchd_label():
    """A daemon whose label a row owns IS that row's organ; a second node for it
    is the same fact twice (the 2026-10-05 study's finding, still open on 10-07)."""
    owned = set(_owners())
    twice = sorted(nid for nid, n in _body_plan()["nodes"].items()
                   if n["level"] == "organ" and nid.startswith("daemon:")
                   and nid.split(":", 1)[1] in owned)
    assert not twice, f"organ nodes that are a row's launchd job counted again: {twice}"


def test_a_local_backend_is_served_by_a_row_that_owns_its_daemon():
    """MEASURED 2026-10-06: backend:ollama (core cells bind it) had no edge to
    any row, and its daemon sat in openclaw's row as a helper — so cutting off
    openclaw looked free. A local backend names its server in `served_by:`."""
    backends = yaml.safe_load((REPO / "state/habitat/llm-backends.yml").read_text(encoding="utf-8"))["backends"]
    rows = {r["id"]: r for r in _manifest()["services"]}
    edges = {(e["from"], e["to"]) for e in json.loads(
        (REPO / "state/anatomy-graph.json").read_text(encoding="utf-8"))["edges"]}
    bad = []
    for name, b in backends.items():
        if not b.get("local"):
            continue
        row = rows.get(b.get("served_by"))
        if not row or not row.get("launchd_label"):
            bad.append(f"{name}: served_by {b.get('served_by')!r} is no manifest row with a launchd_label")
        elif (f"service:{row['id']}", f"backend:{name}") not in edges:
            bad.append(f"{name}: no graph edge service:{row['id']} -> backend:{name}")
    assert not bad, "\n".join(bad)
