"""Anatomy gate — the recall set must contain the host organs it documents.

`tools/keap-recall-queries.py` transcribes every `**Trigger:**` phrase in
`docs/systems/<svc>/SKILLS.md` into KEAP's recall fixture: query -> the skill
card and the system node that must win it. That fixture IS the benchmark
proving the router answers "is Pulse running" with the Pulse skill card rather
than with `node:nos`.

Until 2026-07-26 the tool dropped every manifest row with `stack: null` — it
read the null as "no stack known" and skipped the service. `stack: null` is not
absence: it is the HOST bucket, and `keap_selfmodel_gen.build_slug_model`
models those rows as `nos.host.<svc>` (`s.get("stack") or HOST_STACK`). Since
every Docker service has a stack, the path was never exercised — until this
branch authored SKILLS.md for the twelve host-native organs. 140 of 593 cases
then vanished, every one of them a trigger for wing / bone / pulse / cortex /
hermes / openclaw / opencode / backup / backrest / alloy / tailscale /
iiab-terminal, and the only signal was a stderr WARN naming those services
exactly as if they had no docs at all.

The consequence is the failure this whole layer exists to remove: the gate that
is supposed to catch an ancestor outranking a skill could not hold a single
host-organ case, so the router could regress on all of them and stay green.

Nothing in CI runs `--check`, so the staleness of the committed fixture was
likewise unobservable. It is checked here.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "keap-recall-queries.py"
SELFMODEL_GEN = REPO / "files" / "anatomy" / "scripts" / "keap_selfmodel_gen.py"
MANIFEST = REPO / "state" / "manifest.yml"
DOCS = REPO / "docs" / "systems"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def tool():
    return _load(TOOL, "keap_recall_queries")


def _null_stack_ids() -> list[str]:
    """Manifest ids whose row declares `stack: null` — read from the file."""
    text = MANIFEST.read_text(encoding="utf-8")
    rows = re.findall(r"^  - id: (?P<id>\S+)\s*$(?P<body>.*?)(?=^  - id: |\Z)",
                      text, re.MULTILINE | re.DOTALL)
    out = []
    for sid, body in rows:
        for ln in body.splitlines():
            m = re.match(r"^    stack:\s*(\S+)\s*$", ln)
            if m and m.group(1) in ("null", "~"):
                out.append(sid)
    return out


def test_manifest_actually_has_host_rows():
    """Guard the guard: if nothing is stack:null the rest proves nothing."""
    assert _null_stack_ids(), "no `stack: null` rows in state/manifest.yml"


def test_host_bucket_matches_the_self_model_generator(tool):
    """One bucket name, read from the generator that mints the node ids."""
    sm = _load(SELFMODEL_GEN, "keap_selfmodel_gen")
    assert tool.HOST_STACK == sm.HOST_STACK, (
        f"recall tool buckets host rows as {tool.HOST_STACK!r} but the taxonomy "
        f"is generated with {sm.HOST_STACK!r} — every host case would then "
        f"expect a node that does not exist."
    )


def test_null_stack_rows_resolve_to_the_host_bucket(tool):
    stacks = tool.load_manifest_stacks()
    for sid in _null_stack_ids():
        entry = stacks.get(tool.join_key(sid))
        assert entry is not None, f"{sid} lost from the manifest scan"
        assert entry[1] == tool.HOST_STACK, (
            f"{sid} has `stack: null` and resolved to {entry[1]!r}. Null is the "
            f"HOST bucket, not a missing value — a None here drops the service "
            f"from the recall set entirely."
        )


def test_documented_host_organs_produce_recall_cases(tool):
    """The regression, stated as the thing it broke: Pulse's own triggers."""
    doc = tool.build()
    cases = doc["cases"]
    host = [c for c in cases
            if any(e.startswith("node:nos.host.") for e in c["expect"])]
    assert host, (
        "not one recall case names a host organ, yet docs/systems holds SKILLS.md "
        "for pulse, wing, bone, cortex, hermes, openclaw, backup and tailscale. "
        "The `stack: null` rows are being dropped."
    )

    pulse = [c for c in cases if "node:nos.host.pulse" in c["expect"]]
    assert pulse, "no recall case expects node:nos.host.pulse"
    queries = {c["q"] for c in pulse}
    # Verbatim from docs/systems/pulse/SKILLS.md Trigger lines.
    for q in ("is Pulse running", "restart Pulse", "pulse log",
              "add a job to the catalog"):
        assert q in queries, f"{q!r} authored in SKILLS.md but absent from the set"

    # The forbid half is the point: the ancestors must not win the query.
    for case in pulse:
        assert "node:nos" in case["forbid"]
        assert "node:nos.host" in case["forbid"]


def test_every_documented_system_is_matched(tool):
    """The WARN path must be empty — a stderr line is not a gate."""
    covered = set()
    for c in tool.build()["cases"]:
        covered |= {e.split(":", 1)[1] for e in c["expect"] if e.startswith("node:")}
    documented = sorted(p.parent.name for p in DOCS.glob("*/SKILLS.md")
                        if p.parent.name != "TEMPLATE")
    stacks = tool.load_manifest_stacks()
    missing = [d for d in documented if tool.join_key(d) not in stacks]
    assert not missing, (
        f"documented systems with no manifest row: {missing}. Their SKILLS.md "
        f"triggers are silently absent from the recall benchmark."
    )


def test_committed_fixture_is_fresh(tool):
    """`--check` exists but nothing runs it; run it here.

    The committed fixture is what KEAP's recall gate reads (recall-gate.md §6),
    so a stale one benchmarks documentation that no longer exists.
    """
    out = tool.DEFAULT_OUT
    assert out.is_file(), f"{out} missing — run tools/keap-recall-queries.py"
    committed = json.loads(out.read_text(encoding="utf-8"))
    assert committed == tool.build(), (
        f"{out.relative_to(REPO)} is stale against docs/systems/*/SKILLS.md — "
        f"run `python3 tools/keap-recall-queries.py` and commit the result."
    )
