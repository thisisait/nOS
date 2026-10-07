"""Anatomy gate: Bone's and Wing's event whitelists both equal one spec.

files/anatomy/contracts/event-types.yml is the list. Before it, the two
whitelists were pinned only to each other, type by type, by hand-named
assertions (mirror-parity) — blind to a type both lacked and to one side
carrying a type nobody had named. MEASURED 2026-10-07: Bone carried seven
types Wing refused (remediator_report and six dotted names such as
`scan.batch_done`, which the older extractor's `[a-z0-9_]` could not see).
"""

from __future__ import annotations

import json
import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SPEC = REPO / "files/anatomy/contracts/event-types.yml"
BONE = REPO / "files/anatomy/bone/events.py"
WING = REPO / "files/anatomy/wing/app/Model/EventRepository.php"
ANSIBLE = REPO / "state/schema/event.schema.json"


def _spec() -> list[str]:
    return yaml.safe_load(SPEC.read_text(encoding="utf-8"))["types"]


def _whitelist(path: pathlib.Path) -> set[str]:
    """Quoted names in the VALID_TYPES literal; comments stripped before the
    closer is found (a `}` inside a comment ended the slice early once)."""
    stripped = "\n".join(
        line.split("//")[0].split("#")[0] for line in path.read_text(encoding="utf-8").splitlines()
    )
    start = stripped.index("VALID_TYPES")
    end = stripped.index("]" if path.suffix == ".php" else "}", start)
    return set(re.findall(r"['\"]([a-z][a-z0-9_.]*[a-z0-9])['\"]", stripped[start:end]))


def test_the_spec_is_a_sorted_set() -> None:
    types = _spec()
    assert len(types) >= 60, f"only {len(types)} types read from {SPEC.name}"
    assert types == sorted(set(types)), "event-types.yml: keep `types` sorted, no duplicates"


def _diff(side: set[str]) -> str:
    spec = set(_spec())
    return f"missing {sorted(spec - side)}, extra {sorted(side - spec)}"


def test_bones_whitelist_is_the_spec() -> None:
    bone = _whitelist(BONE)
    assert bone == set(_spec()), f"Bone events.py VALID_TYPES != event-types.yml: {_diff(bone)}"


def test_wings_whitelist_is_the_spec() -> None:
    wing = _whitelist(WING)
    assert wing == set(_spec()), f"Wing EventRepository::VALID_TYPES != event-types.yml: {_diff(wing)}"


def test_the_ansible_event_schema_is_a_subset() -> None:
    enum = set(json.loads(ANSIBLE.read_text(encoding="utf-8"))["properties"]["type"]["enum"])
    assert enum <= set(_spec()), f"event.schema.json types not in the spec: {sorted(enum - set(_spec()))}"
