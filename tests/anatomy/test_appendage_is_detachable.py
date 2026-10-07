"""Anatomy gate — an appendage can be cut off and the core does not notice.

WHY (Fable reflection, accepted 2026-10-06; ssot/doctrine/body-plan.md §4.2). An
appendage is an organ attached through one declared joint (a cross-repo
contract), which no core organ depends on or imports. A row says so in
state/manifest.yml with `joint:` (the spec) or `joint_pending:` (why not yet).

What it reads, all artifacts:
  (a) state/anatomy-graph.json — no dependency edge (data, trigger, temporal; the
      SSO chain collapsed as tools/anatomy-graph-gen.py does) runs from an
      appendage's nodes to a core node. Core = every service: and daemon: node
      that no appendage row owns. Not "infra stacks only": an appendage the
      long tail depends on is not detachable either.
  (b) no import statement in files/anatomy/{wing,bone,pulse} and no line of a
      roles/pazny.{wing,bone,pulse,keap}/templates file names an appendage's
      source location (its tree, its role, its *_dir/_home/_src/_path vars);
  (c) `joint:` is a spec with `contract_version:` and a `fixture:` that exists;
  (d) `joint_pending:` rows are PENDING_JOINTS, which may only shrink;
  (e) tools/body.py marks exactly these rows as appendages.

CEILING. Config coupling is not an import or a mount and passes: Bone reads
face_vfs_token, Wing can arm openclaw as an LLM backend, bone_registry_dir
defaults into openclaw_projects_dir. KEAP's code lives in its own repo; only
its role's templates are read. A backend counts through `served_by:`
(state/llm-backends.yml): an appendage serving one a core agent binds is red.
Ollama has its own core row since 2026-10-06, so openclaw no longer serves it.
"""
from __future__ import annotations

import ast
import copy
import functools
import importlib.util
import json
import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
GRAPH = REPO / "state" / "anatomy-graph.json"
MANIFEST = REPO / "state" / "manifest.yml"
SCHEMA = REPO / "state" / "schema" / "manifest.schema.json"
CORE_CODE = ("wing", "bone", "pulse")
CORE_ROLES = ("wing", "bone", "pulse", "keap")

#: Appendages without a contract yet, 2026-10-06. Only ever delete lines.
PENDING_JOINTS = {"hermes", "openclaw", "openhuman", "nos_forum"}


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@functools.lru_cache(maxsize=None)
def _gen():
    return _load("anatomy_graph_gen", REPO / "tools" / "anatomy-graph-gen.py")


@functools.lru_cache(maxsize=None)
def _rows() -> tuple[dict, ...]:
    return tuple(yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["services"])


def _appendages() -> dict[str, dict]:
    return {r["id"]: r for r in _rows() if r.get("joint") or r.get("joint_pending")}


def _trees(aid: str) -> tuple[str, ...]:
    return (f"files/anatomy/{aid}/", f"roles/pazny.{aid}/")


def _owned(graph: dict, aid: str, row: dict) -> set[str]:
    """service:<id>, its launchd daemons, and nodes sourced from its own tree."""
    labels = [row.get("launchd_label"), *(row.get("launchd_helpers") or [])]
    own = {f"service:{aid}", *(f"daemon:{lb}" for lb in labels if lb)}
    own |= {n for n, v in graph["nodes"].items()
            if str(v.get("source") or "").startswith(_trees(aid))}
    return own & set(graph["nodes"])


def _core_dependents(graph: dict) -> list[str]:
    """'appendage-node -> core-node (kind)' for every edge a core node depends on."""
    apps = _appendages()
    owned = {n: aid for aid, row in apps.items() for n in _owned(graph, aid, row)}
    core = {n for n in graph["nodes"]
            if n.startswith(("service:", "daemon:")) and n not in owned}
    out = [f"{f} -> {t} (data, SSO collapsed)"
           for f, ts in _gen()._service_projection(graph["edges"]).items()
           if f in owned for t in ts if t in core]
    out += [f"{e['from']} -> {e['to']} ({e['kind']})" for e in graph["edges"]
            if e["kind"] in _gen().EDGE_KINDS and e["kind"] != "data"
            and e["from"] in owned and e["to"] in core]
    # An appendage serving an LLM backend a core agent binds (2026-10-06).
    served = {e["to"]: e["from"] for e in graph["edges"] if e["kind"] == "data"
              and e["from"] in owned and e["to"].startswith("backend:")}
    out += [f"{served[e['from']]} -> {e['to']} (via {e['from']})" for e in graph["edges"]
            if e["kind"] == "data" and e["from"] in served
            and e["to"].startswith("agent:") and e["to"] not in owned]
    return sorted(set(out))


def _tokens(aid: str) -> re.Pattern:
    """An appendage's source location: its tree, its role, its path variables."""
    return re.compile(rf"(files/anatomy/{aid}/|pazny\.{aid}\b|\b{aid}_\w*(dir|home|src|path)\b)")


def _imports(path: pathlib.Path, text: str) -> list[str]:
    """The import statements of one file, as strings."""
    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return [f"UNPARSEABLE {path}"]
        mods: list[str] = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods += [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                mods.append(n.module or "")
        return mods
    return re.findall(r"^\s*(?:use|require(?:_once)?|include(?:_once)?|import)\b[^\n]*"
                      r"|\brequire\(\s*['\"][^'\"]+['\"]\s*\)", text, re.M)


def _import_hits(aid: str, path: pathlib.Path, text: str) -> list[str]:
    rx = _tokens(aid)
    seg = re.compile(rf"(^|[./\\]){aid}($|[./\\])")
    return [s for s in _imports(path, text)
            if s.startswith("UNPARSEABLE") or rx.search(s)
            or (path.suffix == ".py" and seg.search(s))]


def _template_hits(aid: str, text: str) -> list[str]:
    rx = _tokens(aid)
    return [ln.strip() for ln in text.splitlines()
            if rx.search(ln) and not ln.lstrip().startswith(("#", "{#"))]


def _code_files():
    for organ in CORE_CODE:
        for p in sorted((REPO / "files" / "anatomy" / organ).rglob("*")):
            if (p.is_file() and p.suffix in (".py", ".php", ".ts", ".js", ".mjs")
                    and not {"vendor", "node_modules", "temp"} & set(p.parts)):
                yield p


def _joint_problems(aid: str, joint: str) -> list[str]:
    spec = REPO / joint
    if not spec.is_file():
        return [f"{aid}: joint {joint} is not a file"]
    text = spec.read_text(encoding="utf-8")
    bad = [] if re.search(r"^contract_version:\s*\d+", text, re.M) else [
        f"{aid}: joint {joint} has no `contract_version:`"]
    fx = re.search(r"^fixture:\s*(\S+)", text, re.M)
    if not (fx and (REPO / fx.group(1)).exists()):
        bad.append(f"{aid}: joint {joint} names no existing `fixture:`")
    return bad


# ── the gates ─────────────────────────────────────────────────────────────


def test_the_schema_declares_the_joint():
    props = json.loads(SCHEMA.read_text(encoding="utf-8"))["definitions"]["service"]["properties"]
    assert {"joint", "joint_pending"} <= set(props)


def test_a_core_node_never_depends_on_an_appendage():
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    missing = sorted(f"service:{a}" for a in _appendages() if f"service:{a}" not in graph["nodes"])
    assert not missing, f"appendage rows with no graph node — regenerate the graph: {missing}"
    bad = _core_dependents(graph)
    assert not bad, ("the core depends on an appendage, so it cannot be cut off "
                     "(body-plan.md §4.2):\n  " + "\n  ".join(bad))


def test_a_planted_dependency_goes_red():
    """(a) can go red: one edge from face to Wing in a copy of the graph."""
    graph = copy.deepcopy(json.loads(GRAPH.read_text(encoding="utf-8")))
    graph["edges"].append({"from": "service:face", "to": "service:wing", "kind": "data"})
    assert "service:face -> service:wing (data, SSO collapsed)" in _core_dependents(graph)
    graph["edges"][-1]["kind"] = "trigger"
    assert "service:face -> service:wing (trigger)" in _core_dependents(graph)
    graph["edges"].append({"from": "service:openclaw", "to": "backend:ollama", "kind": "data"})
    assert "service:openclaw -> agent:jeff (via backend:ollama)" in _core_dependents(graph)


def test_core_code_and_templates_never_name_an_appendage_source():
    bad = []
    for p in _code_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        bad += [f"{p.relative_to(REPO)}: {s}" for a in _appendages() for s in _import_hits(a, p, text)]
    for role in CORE_ROLES:
        for p in sorted((REPO / "roles" / f"pazny.{role}" / "templates").glob("*")):
            text = p.read_text(encoding="utf-8", errors="replace")
            bad += [f"{p.relative_to(REPO)}: {s}" for a in _appendages() for s in _template_hits(a, text)]
    assert not bad, "a core organ imports or mounts an appendage:\n  " + "\n  ".join(bad)


def test_the_import_and_mount_readers_can_go_red():
    py, php = pathlib.Path("x.py"), pathlib.Path("x.php")
    assert _import_hits("face", py, "from face.lib import uid\n")
    assert _import_hits("hermes", php, "require_once '../../roles/pazny.hermes/x.php';\n")
    assert not _import_hits("face", py, "# files/anatomy/face/ is read by hand\nimport json\n")
    assert _template_hits("face", "      - {{ face_src_dir }}:/face:ro\n")
    assert not _template_hits("face", "      KEAP_EMBED_ORIGINS: https://{{ face_domain }}\n")
    assert not _template_hits("face", "{# files/anatomy/face/ #}\n")


def test_every_joint_is_a_spec_with_a_fixture():
    bad = [p for a, r in _appendages().items() if r.get("joint") for p in _joint_problems(a, r["joint"])]
    assert not bad, "\n  ".join(["a joint must be a contract (cross-repo-contracts.md §1):", *bad])
    assert _joint_problems("x", "state/manifest.yml"), "the joint reader cannot go red"


def test_appendages_without_a_contract_only_shrink():
    pending = {a for a, r in _appendages().items() if r.get("joint_pending")}
    assert pending == PENDING_JOINTS, (
        f"new appendages without a contract: {sorted(pending - PENDING_JOINTS)} — write the "
        f"contract and set `joint:`; contracts landed (delete from PENDING_JOINTS): "
        f"{sorted(PENDING_JOINTS - pending)}")


def test_body_marks_exactly_the_appendage_rows():
    body = _load("nos_body", REPO / "tools" / "body.py")
    marked = {r["id"] for r in _rows() if (body.appendage(f"service:{r['id']}") or "").startswith("appendage")}
    assert marked == set(_appendages())
    assert body.appendage("service:keap") is None, "KEAP has a contract and is not an appendage"
