"""The public projection — internal anatomy artifact -> public document.

This module is the boundary the apex site lives behind. It is a pure
transform with a gate in front of it, and the gate is the point:

  * Every field the artifact carries must have a ruling in ruling.yml —
    VERBATIM, TRANSFORMED, or WITHHELD. An UNRULED field HALTS the build
    (``GateError``), so a generator commit that grows the artifact cannot
    ship a new field to the public page; someone must rule on it first.
  * The diff runs BOTH directions: a ruled field that no longer exists in
    the artifact is a stale ruling and halts too.
  * Every node must have a ruling. The published node set is FROZEN by the
    ruling file (decision D4): a new artifact node halts the build, and a
    ruled node that vanished halts the build. Absence must not be an
    oracle.
  * The forbidden set for the leak check is derived from the INPUT
    artifact (ids, withheld string values, service name tokens), not from
    the output — the gate cannot be satisfied by editing the output, and
    editing the gate's own allow-list is a visible edit to a signable
    ruling file.

Nothing here reads the clock, the estate, or anything live. Building
twice yields byte-identical output; the determinism test pins that.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

APEX_DIR = Path(__file__).resolve().parent
REPO = APEX_DIR.parents[2]

ARTIFACT_PATH = REPO / "state" / "anatomy-graph.json"
RULING_PATH = APEX_DIR / "ruling.yml"

PUBLIC_SCHEMA = "thisisait/public-anatomy"

RULINGS = {"VERBATIM", "TRANSFORMED", "WITHHELD"}

#: W3C syntax tokens masked before the leak scan. These are spellings the
#: platform imposes (CSS at-rules and property names), not content — e.g.
#: ``@font-face`` collides with the withheld service token ``face`` and
#: the CSS ``outline`` property with a product name. Masking is limited
#: to the exact syntax position (at-rule, or property followed by ``:``).
_SYNTAX_MASKS = (
    re.compile(r"@font-face"),
    re.compile(r"\boutline(?=\s*:)"),
)


class GateError(RuntimeError):
    """The build must halt: a ruling is missing, stale, or inconsistent."""


class LeakError(RuntimeError):
    """A withheld term reached the public output."""


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def load_artifact(path: Path = ARTIFACT_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_ruling(path: Path = RULING_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        ruling = yaml.safe_load(fh)
    for axis in ("artifact", "node", "edge"):
        if axis not in ruling.get("fields", {}):
            raise GateError(f"ruling.yml lacks the `fields.{axis}` table")
    if "nodes" not in ruling or "organs" not in ruling:
        raise GateError("ruling.yml lacks `nodes` or `organs`")
    return ruling


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------

def field_census(artifact: dict) -> dict[str, set[str]]:
    """Every key the artifact actually carries, per axis."""
    node_keys: set[str] = set()
    for node in artifact["nodes"].values():
        node_keys.update(node.keys())
    edge_keys: set[str] = set()
    for edge in artifact["edges"]:
        edge_keys.update(edge.keys())
    return {
        "artifact": set(artifact.keys()),
        "node": node_keys,
        "edge": edge_keys,
    }


def gate_fields(artifact: dict, ruling: dict) -> None:
    census = field_census(artifact)
    tally = {"VERBATIM": 0, "TRANSFORMED": 0, "WITHHELD": 0}
    for axis, actual in census.items():
        table = ruling["fields"][axis]
        for name, row in table.items():
            verdict = (row or {}).get("ruling")
            if verdict not in RULINGS:
                raise GateError(
                    f"field `{axis}.{name}` has no valid ruling "
                    f"(got {verdict!r}; must be one of {sorted(RULINGS)})"
                )
            tally[verdict] += 1
        unruled = actual - set(table)
        if unruled:
            raise GateError(
                f"UNRULED {axis} field(s) {sorted(unruled)} — the artifact "
                "gained a field nobody has ruled on. Add a ruling to "
                "files/anatomy/apex/ruling.yml before this build may run."
            )
        stale = set(table) - actual
        if stale:
            raise GateError(
                f"STALE ruling(s) for {axis} field(s) {sorted(stale)} — "
                "ruled but no longer present in the artifact. Re-rule."
            )
    declared = ruling.get("splits", {})
    actual_split = {k.lower(): v for k, v in tally.items()}
    if actual_split != {k: int(v) for k, v in declared.items()}:
        raise GateError(
            f"ruling split ledger disagrees with the table: declared "
            f"{declared}, counted {actual_split}. Edit both consciously."
        )


def gate_nodes(artifact: dict, ruling: dict) -> None:
    artifact_ids = set(artifact["nodes"].keys())
    ruled = ruling["nodes"]
    ruled_ids = set(ruled.keys())

    unruled = artifact_ids - ruled_ids
    if unruled:
        raise GateError(
            f"UNRULED node(s) {sorted(unruled)[:5]}{'...' if len(unruled) > 5 else ''} "
            f"({len(unruled)} total) — the artifact gained nodes nobody has "
            "ruled on. The published set is frozen (ruling D4)."
        )
    vanished = ruled_ids - artifact_ids
    if vanished:
        raise GateError(
            f"RULED node(s) no longer in the artifact: {sorted(vanished)} — "
            "a frozen set may not silently shrink (ruling D4). Re-rule."
        )

    organs = set(ruling["organs"].keys())
    for nid, verdict in ruled.items():
        if verdict == "withheld":
            continue
        if not isinstance(verdict, dict) or "publish" not in verdict:
            raise GateError(f"node `{nid}`: ruling must be `withheld` or a publish mapping")
        if artifact["nodes"][nid].get("kind") != "service":
            raise GateError(f"node `{nid}`: only `service` nodes may publish (field ruling on node.kind)")
        if verdict["publish"] not in organs:
            raise GateError(f"node `{nid}` publishes into unknown organ `{verdict['publish']}`")
        speaks = verdict.get("speaks", "")
        if not speaks or not isinstance(speaks, str):
            raise GateError(f"node `{nid}`: a published atom must carry a `speaks:` phrase")


def gate(artifact: dict, ruling: dict) -> None:
    gate_fields(artifact, ruling)
    gate_nodes(artifact, ruling)
    _gate_amnesty(artifact, ruling)


def _service_tokens(artifact: dict) -> set[str]:
    """The name tokens of every service node, in the spellings a page
    could plausibly render (underscore, dash, space)."""
    tokens: set[str] = set()
    for nid, node in artifact["nodes"].items():
        if node.get("kind") != "service":
            continue
        tail = nid.split(":", 1)[1]
        for sep in ("_", "-", " "):
            tokens.add(tail.replace("_", sep))
    return tokens


def _gate_amnesty(artifact: dict, ruling: dict) -> None:
    tails = _service_tokens(artifact)
    for row in ruling.get("vocabulary_amnesty", []):
        term = str(row.get("term", "")).lower()
        if not term:
            raise GateError("vocabulary_amnesty entry without a term")
        if term in tails:
            raise GateError(f"amnesty may never cover a service name: `{term}`")


# ---------------------------------------------------------------------------
# forbidden terms (derived from the INPUT, never from the output)
# ---------------------------------------------------------------------------

def _iter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)


def _harvestable(s: str) -> bool:
    """A withheld string worth forbidding as a substring: long enough and
    shaped like an identifier/path/prose rather than one bare word."""
    return len(s) >= 6 and re.search(r"[^a-zA-Z]", s) is not None


def forbidden_terms(artifact: dict, ruling: dict) -> tuple[set[str], set[str]]:
    """Returns (substrings, word_tokens), all lowercase.

    substrings — matched anywhere in the output text:
      * every node id;
      * every string value of a WITHHELD field harvested from the
        artifact itself, when it is long enough (>= 6) AND carries a
        non-letter character — the shape of identifiers, paths, env vars
        and prose, but not of bare English words ('writes', 'Systems'),
        which as substrings only produce false positives; a bare word
        that IS a product name is caught by the word-token axis;
      * every node description in full (the transform replaces it — the
        artifact string itself must never appear).
    word_tokens — matched on word boundaries:
      * every service name token (underscore/dash/space spellings);
      * every mark in the ruling's forbidden_marks backstop.
    """
    amnesty = {str(r["term"]).lower() for r in ruling.get("vocabulary_amnesty", [])}

    withheld_node = {
        name for name, row in ruling["fields"]["node"].items()
        if row["ruling"] == "WITHHELD"
    }
    withheld_edge = {
        name for name, row in ruling["fields"]["edge"].items()
        if row["ruling"] == "WITHHELD"
    }
    withheld_top = {
        name for name, row in ruling["fields"]["artifact"].items()
        if row["ruling"] == "WITHHELD"
    }

    substrings: set[str] = set()
    for nid, node in artifact["nodes"].items():
        substrings.add(nid.lower())
        for field, value in node.items():
            if field in withheld_node:
                for s in _iter_strings(value):
                    if _harvestable(s):
                        substrings.add(s.lower())
        desc = node.get("description", "")
        if isinstance(desc, str) and len(desc) >= 20:
            substrings.add(desc.lower())
    for edge in artifact["edges"]:
        for field, value in edge.items():
            if field in withheld_edge:
                for s in _iter_strings(value):
                    if _harvestable(s):
                        substrings.add(s.lower())
    for field in withheld_top:
        for s in _iter_strings(artifact.get(field)):
            if _harvestable(s):
                substrings.add(s.lower())

    substrings -= amnesty

    word_tokens = _service_tokens(artifact)
    word_tokens.update(str(m).lower() for m in ruling.get("forbidden_marks", []))
    return substrings, word_tokens


def leak_check(text: str, artifact: dict, ruling: dict) -> None:
    """Refuse output that carries any withheld term. Case-insensitive."""
    lowered = text.lower()
    for mask in _SYNTAX_MASKS:
        lowered = mask.sub(" ", lowered)
    substrings, word_tokens = forbidden_terms(artifact, ruling)
    for term in sorted(substrings):
        if term in lowered:
            raise LeakError(f"withheld term reached the public output: {term!r}")
    for token in sorted(word_tokens):
        if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", lowered):
            raise LeakError(f"forbidden mark reached the public output: {token!r}")


# ---------------------------------------------------------------------------
# the projection itself
# ---------------------------------------------------------------------------

_LIMB_ORDER = {"core": 0, "left": 1, "right": 2}


def project(artifact: dict, ruling: dict) -> dict:
    """Artifact + ruling -> the public document. Runs the gate first."""
    gate(artifact, ruling)

    published: dict[str, dict] = {}   # internal id -> {organ, speaks}
    for nid, verdict in ruling["nodes"].items():
        if isinstance(verdict, dict):
            published[nid] = {"organ": verdict["publish"], "speaks": verdict["speaks"]}

    organs_out = []
    for oid, meta in ruling["organs"].items():
        atoms = sorted(
            row["speaks"] for row in published.values() if row["organ"] == oid
        )
        organs_out.append({
            "id": oid,
            "title": meta["title"],
            "tells": meta["tells"],
            "limb": meta["limb"],
            "order": int(meta["order"]),
            "atoms": [{"speaks": s} for s in atoms],
        })
    organs_out.sort(key=lambda o: (_LIMB_ORDER[o["limb"]], o["order"]))

    veins: dict[tuple[str, str], set[str]] = {}
    for edge in artifact["edges"]:
        src = published.get(edge["from"])
        dst = published.get(edge["to"])
        if not src or not dst:
            continue
        a, b = src["organ"], dst["organ"]
        if a == b:
            continue
        key = tuple(sorted((a, b)))
        veins.setdefault(key, set()).add(edge["kind"])
    veins_out = [
        {"between": list(pair), "kind": sorted(kinds)}
        for pair, kinds in sorted(veins.items())
    ]

    return {
        "schema": PUBLIC_SCHEMA,
        "version": artifact["version"],
        "counts": {
            "organs": len(organs_out),
            "atoms": sum(len(o["atoms"]) for o in organs_out),
            "veins": len(veins_out),
        },
        "organs": organs_out,
        "veins": veins_out,
    }


def public_json(artifact: dict, ruling: dict) -> str:
    doc = project(artifact, ruling)
    text = json.dumps(doc, indent=1, ensure_ascii=True, sort_keys=False) + "\n"
    leak_check(text, artifact, ruling)
    return text
