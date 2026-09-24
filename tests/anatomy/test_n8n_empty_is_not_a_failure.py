"""A pack workflow that finds nothing to do must answer 200, not 500.

MEASURED 2026-09-24. `ares-verify:registry-new` fires `--scope=missing` every
fifteen minutes and had been rc=2 since 01:23 UTC, reporting
"n8n-fire: HTTP 500 (import+activate the template?)" — a guess, and the wrong
one: both workflows were published. n8n's own execution list said every run
SUCCEEDED. The node tally of execution 48:

    Webhook       items=1
    Fetch IČOs    items=1
    Fetch status  items=1
    Select IČOs   items=0     <- lastNodeExecuted

`scope=missing` selects parties with no registry status yet; the runs at 17:09
and 17:23 UTC filled them all in. With `responseMode: lastNode`, a flow that
ends on an empty node has no body to return, so n8n answered 500 and the clock
recorded a failure. THE JOB WAS FAILING BECAUSE IT HAD SUCCEEDED — four times
an hour, which is how an operator learns to ignore a channel.

This pins the shape, not the wording: any pack whose selection can legitimately
come up empty must (a) still emit an item and (b) route it somewhere terminal,
so the caller gets a 200 that SAYS nothing was due. A genuine failure is
unaffected — the execution errors and the status code is not 200.
"""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PACKS = ROOT / "files/anatomy/n8n/packs"


def _graph(pack_yml):
    pack = yaml.safe_load(pack_yml.read_text(encoding="utf-8")) or {}
    ref = pack.get("graph") or pack.get("workflow")
    return json.loads((PACKS / ref).read_text(encoding="utf-8")), pack


def _last_node_mode_packs():
    """Packs whose webhook returns the final node's data — the ones at risk."""
    out = []
    for y in sorted(PACKS.glob("*.yml")):
        graph, pack = _graph(y)
        for n in graph.get("nodes", []):
            if n.get("type", "").endswith(".webhook"):
                if (n.get("parameters") or {}).get("responseMode") == "lastNode":
                    out.append((y.name, graph))
                    break
    return out


def test_the_ares_selection_cannot_end_the_flow_empty():
    graph, _ = _graph(PACKS / "nos-pull-ares-registry.yml")
    nodes = {n["name"]: n for n in graph["nodes"]}
    select = next(n for k, n in nodes.items() if k.startswith("Select"))
    code = (select.get("parameters") or {}).get("jsCode", "")
    assert "out.length === 0" in code and "noop" in code, (
        "the selection node can still return [] — an empty selection would "
        "leave it last-executed with no data and the webhook would answer 500"
    )


def test_the_empty_branch_goes_somewhere_terminal():
    """Emitting a sentinel is half a fix if it then flows into the work path."""
    graph, _ = _graph(PACKS / "nos-pull-ares-registry.yml")
    conns = graph["connections"]
    select = next(k for k in conns if k.startswith("Select"))
    after = [c["node"] for c in conns[select]["main"][0]]
    assert after == ["Anything to verify?"], (
        f"the selection feeds {after} directly — the noop sentinel would be "
        "passed to the fetch path as if it were a party"
    )
    branches = conns["Anything to verify?"]["main"]
    assert len(branches) == 2, "the guard must have both a true and a false branch"
    true_branch = [c["node"] for c in branches[0]]
    false_branch = [c["node"] for c in branches[1]]
    assert true_branch == ["Fetch ARES"], true_branch
    assert false_branch and false_branch[0] not in ("Fetch ARES", "Fetch ADIS"), (
        f"the empty branch reaches the work path: {false_branch}"
    )
    # The terminal node must exist and produce data, or we are back at 500.
    terminal = {n["name"]: n for n in graph["nodes"]}[false_branch[0]]
    assert terminal["type"].endswith((".set", ".noOp", ".code")), (
        f"the empty branch ends on {terminal['type']}, which may produce no data — "
        "the webhook is back to having nothing to return"
    )


def test_every_last_node_pack_is_covered_by_this_reasoning():
    """If a new pack adopts responseMode lastNode, this gate must be revisited.

    Not a shape assertion — a tripwire. The failure mode is specific to
    `lastNode`, so a new pack using it is a new place the same 500 can appear.
    """
    covered = {"nos-pull-ares-registry.yml"}
    at_risk = {name for name, _ in _last_node_mode_packs()}
    assert at_risk <= covered, (
        f"new pack(s) using responseMode=lastNode: {sorted(at_risk - covered)} — "
        "each can answer 500 on an empty result; add the noop guard and list it here"
    )
