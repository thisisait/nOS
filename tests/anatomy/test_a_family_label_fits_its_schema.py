"""A hand-written label must be an answer the agent's schema can accept.

The harness takes the agent as a FLAG (`--agent ops-extract`), and the family
directory says nothing about which schema its labels were written against. So
scoring a family against the wrong agent is a single mistyped word — and the
report it produces does not look like a mistake. Every sample comes back
`invalid_chain`, the summary reads "the model emitted nothing the schema would
accept at any size", and that is a capability finding about a flag.

MEASURED 2026-08-30, and this is not hypothetical in the smaller form: with
`required` listing all three fields, `invoice-absent`'s labels — which OMIT a
field by design — were unrepresentable, both models scored 2/10, and the
conclusion drawn was about model size. It was the contract. Same failure, one
level up: a label the schema cannot express turns into a statement about the
model.

So each family now DECLARES its agent, and this checks the labels against that
agent's `one_shot.schema.json` with the same subset `App\\AgentKit\\OneShot`
implements: type, required, enum, and `additionalProperties: false`. It is not
a JSON-Schema library and does not want to be — it is the same handful of
rules, and a family whose labels need more than that has outgrown one_shot.

Retro-verified 2026-08-30 by pointing weakness-triage at ops-extract.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
FAMILIES = REPO / "state/ops-task-families"
AGENTS = REPO / "files/anatomy/agents"

_TYPES = {"string": str, "number": (int, float), "boolean": bool,
          "object": dict, "array": list}


def _families() -> list[pathlib.Path]:
    return sorted(p for p in FAMILIES.iterdir() if (p / "family.yml").exists())


def test_there_are_families_to_check() -> None:
    """Without this, every parametrised test below vacuously passes on an
    empty directory — the shape of green that means nothing ran."""
    assert len(_families()) >= 2, "fewer than two task families; is the path right?"


@pytest.mark.parametrize("family", _families(), ids=lambda p: p.name)
def test_every_label_validates_against_the_declared_schema(family: pathlib.Path) -> None:
    meta = yaml.safe_load((family / "family.yml").read_text(encoding="utf-8")) or {}
    agent = meta.get("agent")
    assert agent, (
        f"{family.name}/family.yml declares no `agent:`. The harness would take "
        "one from a flag and nothing would check that its schema can express "
        "these labels.")
    schema_path = AGENTS / agent / "one-shot.schema.json"
    assert schema_path.exists(), f"{family.name} names agent {agent!r}, which has no one-shot schema"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    props = schema.get("properties") or {}
    required = schema.get("required") or []
    closed = schema.get("additionalProperties") is False

    for line in (family / "samples.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        sample = json.loads(line)
        label, at = sample["expect"], f"{family.name}/{sample['id']}"
        for key in required:
            assert key in label, f"{at}: label omits required field {key!r} — it can never score exact"
        for key, value in label.items():
            if closed:
                assert key in props, f"{at}: label carries {key!r}, which the schema forbids"
            spec = props.get(key) or {}
            want = _TYPES.get(spec.get("type"))
            if want:
                assert isinstance(value, want) and not isinstance(value, bool) or spec.get("type") == "boolean", (
                    f"{at}: {key}={value!r} is not a {spec['type']}")
            if spec.get("enum"):
                assert value in spec["enum"], (
                    f"{at}: {key}={value!r} is not one of {spec['enum']} — "
                    "the schema would reject the correct answer")
