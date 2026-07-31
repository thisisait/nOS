#!/usr/bin/env python3
"""Emit per-runtime artifacts from the nOS genome. One declaration, N languages.

WHY A GENERATOR AND NOT A TRANSPILER
------------------------------------
The estate has answered this question three times already and never with a
transpiler:

  * KEAP (TS) and Wing (PHP) agree on cortex opcodes via a hash-compared `cx1:`
    registry plus a boot gate — Wing refuses to start if a published opcode has
    no handler.
  * Error shapes are byte-identical, enforced by
    tests/anatomy/test_cortex_phase2_uniform_error.py — a PYTHON test asserting
    that a PHP service matches a TYPESCRIPT service's JSON shape.
  * shared/contracts/cortex.ts is lifted verbatim into the organ with a
    provenance header and a vendoring gate.

The pattern underneath all three is regenerate-and-diff, which already runs in
four places (contracts-drift, spine-render.mjs --check, lift-xrefs +
git diff --exit-code, gdpr-dpa-register.py --check). This is that machinery
pointed at a new source, not new machinery.

The design's own test: adding a fifth runtime must cost ONE emitter, not a
renegotiated contract. If a Rust brain requires reopening the schema, the genome
failed.

WHAT IS DELIBERATELY NOT GENERATED
----------------------------------
Anything that decides what may ACT on an entity. Both nos-cortex-lang.md §2 and
the Wing executor §2 require that a capability must not be addable by data, so
opcodes and handlers stay hand-written per runtime. This emits FACTS — enums,
required-field sets, the residency rule — and nothing else.

Usage:
    python3 tools/genome-codegen.py            # write artifacts
    python3 tools/genome-codegen.py --check    # exit 1 if any artifact is stale
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
GENOME = REPO / "state" / "genome"
ENTITY = GENOME / "entity.schema.json"

PY_TARGET = REPO / "files" / "anatomy" / "module_utils" / "nos_entity.py"
TS_TARGET = REPO / "files" / "anatomy" / "face" / "src" / "lib" / "contracts" / "entity.gen.ts"

BANNER_SRC = "state/genome/entity.schema.json"
GENERATOR = "tools/genome-codegen.py"


# ── read the genome ───────────────────────────────────────────────────────


def load() -> dict:
    return json.loads(ENTITY.read_text())


def facet(schema: dict, name: str) -> dict:
    return schema["definitions"][name]


def enum_of(schema: dict, facet_name: str, prop: str) -> list[str]:
    return facet(schema, facet_name)["properties"][prop]["enum"]


def required_of(schema: dict, facet_name: str) -> list[str]:
    return list(facet(schema, facet_name).get("required") or [])


def collect(schema: dict) -> dict:
    """Everything the emitters need, resolved once so they cannot disagree."""
    return {
        "legal_basis": enum_of(schema, "compliance", "legal_basis"),
        "gate": enum_of(schema, "access", "gate"),
        "surface": enum_of(schema, "face", "surface"),
        "compliance_required": required_of(schema, "compliance"),
        "identity_required": required_of(schema, "identity"),
        "access_required": required_of(schema, "access"),
        "entity_required": required_of(schema, "entity"),
        "name_pattern": facet(schema, "identity")["properties"]["name"]["pattern"],
        "justification_min": facet(schema, "access")["properties"]["justification"]["minLength"],
        "tier_min": facet(schema, "access")["properties"]["tier"]["minimum"],
        "tier_max": facet(schema, "access")["properties"]["tier"]["maximum"],
    }


# ── emitters ──────────────────────────────────────────────────────────────


def _py_list(xs: list[str]) -> str:
    return "(\n" + "".join(f'    "{x}",\n' for x in xs) + ")"


def emit_python(g: dict) -> str:
    return f'''"""GENERATED — do not edit. Source: {BANNER_SRC} (via {GENERATOR}).

Consumers: the plugin loader and apps_runner. Editing this file by hand makes
the `contracts-drift` CI job go red, which is the point.
"""
from __future__ import annotations

import re

LEGAL_BASIS = {_py_list(g["legal_basis"])}

ACCESS_GATES = {_py_list(g["gate"])}

FACE_SURFACES = {_py_list(g["surface"])}

IDENTITY_REQUIRED = {_py_list(g["identity_required"])}

COMPLIANCE_REQUIRED = {_py_list(g["compliance_required"])}

ACCESS_REQUIRED = {_py_list(g["access_required"])}

ENTITY_REQUIRED = {_py_list(g["entity_required"])}

NAME_RE = re.compile(r"{g["name_pattern"]}")

JUSTIFICATION_MIN_LENGTH = {g["justification_min"]}
TIER_MIN = {g["tier_min"]}
TIER_MAX = {g["tier_max"]}


def residency_is_consistent(compliance: dict) -> bool:
    """`transfers_outside_eu` is the deprecated inverse of `eu_residency`.

    JSON Schema draft-07 cannot express a cross-field inverse, so the rule lives
    here — and it is a real rule: plugin.schema.json requires `eu_residency`
    while app.schema.json requires `transfers_outside_eu`, which is exactly the
    split nos_gdpr.py exists to paper over. An entity carrying both must not
    contradict itself.
    """
    if "transfers_outside_eu" not in compliance or "eu_residency" not in compliance:
        # Only ONE spelling present: nothing to contradict. This matters — three
        # manifests (hermes, openclaw, vaultwarden) declare residency ONLY as
        # `transfers_outside_eu: false`, which is not a missing field, it is the
        # deprecated spelling used alone. Treating an absent eu_residency as
        # False would flag them as self-contradictory, which is backwards.
        return True
    return bool(compliance["eu_residency"]) != bool(compliance["transfers_outside_eu"])


def ungated_route_needs_justification(access: dict) -> bool:
    """True when this access facet is a REM-144 shape: reachable by anyone, with
    nothing but (at best) a comment behind it."""
    if not access.get("routed"):
        return False
    if access.get("gate") != "none":
        return False
    return len((access.get("justification") or "").strip()) < JUSTIFICATION_MIN_LENGTH
'''


def _ts_union(xs: list[str]) -> str:
    return " | ".join(f"'{x}'" for x in xs)


def _ts_arr(xs: list[str]) -> str:
    return "[" + ", ".join(f"'{x}'" for x in xs) + "] as const"


def emit_typescript(g: dict) -> str:
    return f"""// GENERATED — do not edit. Source: {BANNER_SRC} (via {GENERATOR}).
//
// Replaces the hand-mirrored contract between face and KEAP, which had already
// drifted before this file existed: face's ColumnKind carried 11 kinds to
// KEAP's 12, and every constraint was dropped on the way across. Nothing
// compared them, so a typo'd kind passed nOS CI and failed at KEAP's zod parse
// during the seeder run.

export type LegalBasis = {_ts_union(g["legal_basis"])};
export const LEGAL_BASIS = {_ts_arr(g["legal_basis"])};

export type AccessGate = {_ts_union(g["gate"])};
export const ACCESS_GATES = {_ts_arr(g["gate"])};

export type FaceSurface = {_ts_union(g["surface"])};
export const FACE_SURFACES = {_ts_arr(g["surface"])};

export const IDENTITY_REQUIRED = {_ts_arr(g["identity_required"])};
export const COMPLIANCE_REQUIRED = {_ts_arr(g["compliance_required"])};
export const ACCESS_REQUIRED = {_ts_arr(g["access_required"])};
export const ENTITY_REQUIRED = {_ts_arr(g["entity_required"])};

export const NAME_PATTERN = /{g["name_pattern"]}/;
export const JUSTIFICATION_MIN_LENGTH = {g["justification_min"]};
export const TIER_MIN = {g["tier_min"]};
export const TIER_MAX = {g["tier_max"]};

/** A routed entity with no gate is anonymously reachable — REM-144's shape. */
export function ungatedRouteNeedsJustification(access: {{
  routed?: boolean;
  gate?: AccessGate;
  justification?: string;
}}): boolean {{
  if (!access.routed) return false;
  if (access.gate !== 'none') return false;
  return (access.justification ?? '').trim().length < JUSTIFICATION_MIN_LENGTH;
}}
"""


TARGETS = [
    (PY_TARGET, emit_python),
    (TS_TARGET, emit_typescript),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if any artifact is stale")
    args = ap.parse_args()

    g = collect(load())
    stale = []
    for path, emitter in TARGETS:
        want = emitter(g)
        have = path.read_text() if path.is_file() else None
        if have == want:
            continue
        if args.check:
            stale.append(str(path.relative_to(REPO)))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(want)
        print(f"wrote {path.relative_to(REPO)}")

    if args.check:
        if stale:
            print("STALE generated artifacts:", ", ".join(stale), file=sys.stderr)
            print(f"run `python3 {GENERATOR}` and commit", file=sys.stderr)
            return 1
        print(f"genome artifacts current ({len(TARGETS)} checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
