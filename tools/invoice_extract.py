"""invoice-structured-extractor unit — the offline seam of the local
schema-constrained ISDOC extractor (files/anatomy/agents/{invoice-vision-ocr,
invoice-extract}). At runtime Stage B's actual constraint is Ollama's native
structured-output `format` param (the model literally cannot emit a shape the
schema forbids); validate_record() is the offline STAND-IN proof of that same
contract — a hand-rolled subset validator over
state/schema/isdoc-record.schema.yaml, same style as nos_digest.check_bundle
(no jsonschema dependency, ponytail rung 5: this repo is not carrying that lib
for one schema).

build_sidecar() assembles the state/schema/isdoc-extract-sidecar.schema.yaml
shape from a record + per-field {value, confidence, source}. It NEVER sets
verified:true — the operator-verify rung
(tools/digest-import-vision.py::VisionImporter.parse()) is a deliberate later
act, not something the extraction step gets to grant itself, no matter how
high every field's confidence reads.

Calling an actual Ollama model is OUT OF SCOPE here (build the plumbing +
stub-testable seams, not a live run) — see run_stage_b_stub() for the seam a
real Ollama HTTP call plugs into later.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO / "state" / "schema"

RECORD_SCHEMA = yaml.safe_load((SCHEMA_DIR / "isdoc-record.schema.yaml").read_text(encoding="utf-8"))
SIDECAR_SCHEMA = yaml.safe_load((SCHEMA_DIR / "isdoc-extract-sidecar.schema.yaml").read_text(encoding="utf-8"))
CONFIDENCE_FLOOR = float(SIDECAR_SCHEMA["confidence_floor"])

_TYPE_MAP = {"string": str, "number": (int, float), "array": list, "object": dict, "boolean": bool}


def _validate_value(value, spec: dict, path: str, errors: list[str]) -> None:
    typ = spec.get("type")
    if typ and typ in _TYPE_MAP and not isinstance(value, _TYPE_MAP[typ]):
        errors.append(f"{path}: expected {typ}, got {type(value).__name__}")
        return
    if "enum" in spec and value not in spec["enum"]:
        errors.append(f"{path}: {value!r} not in enum {spec['enum']}")
    if typ == "string" and "pattern" in spec and isinstance(value, str) and not re.match(spec["pattern"], value):
        errors.append(f"{path}: {value!r} does not match pattern {spec['pattern']!r}")
    if typ == "object" and isinstance(value, dict):
        _validate_object(value, spec, path, errors)
    if typ == "array" and isinstance(value, list) and "items" in spec:
        for i, item in enumerate(value):
            _validate_value(item, spec["items"], f"{path}[{i}]", errors)


def _validate_object(obj: dict, spec: dict, path: str, errors: list[str]) -> None:
    props = spec.get("properties") or {}
    if spec.get("additionalProperties") is False:
        unknown = set(obj) - set(props)
        if unknown:
            errors.append(f"{path}: unknown key(s) {sorted(unknown)} (schema forbids additionalProperties)")
    for req in spec.get("required") or []:
        if req not in obj:
            errors.append(f"{path}: missing required key {req!r}")
    for key, val in obj.items():
        if key in props:
            _validate_value(val, props[key], f"{path}.{key}" if path else key, errors)


def validate_record(record: dict, schema: dict | None = None) -> list[str]:
    """Hand-rolled subset validator (type/required/properties/items/enum/
    pattern/additionalProperties) against isdoc-record.schema.yaml — the
    offline proof that a schema-violating record IS rejected, standing in for
    Ollama's constrained decode (which cannot emit the violation at all)."""
    schema = schema or RECORD_SCHEMA
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record is not a mapping"]
    _validate_object(record, schema, "", errors)
    return errors


_ICO_IN_NAME = re.compile(r"(?:I[ČC]O|ICO)\s*(\d{8})", re.I)


def lift_ico_from_party_name(party: dict) -> dict:
    """VLM often jams 'IČO 00000131' into seller.name and omits seller.ico."""
    if not isinstance(party, dict):
        return party
    out = dict(party)
    if out.get("ico"):
        return out
    m = _ICO_IN_NAME.search(str(out.get("name") or ""))
    if not m:
        return out
    out["ico"] = m.group(1)
    out["name"] = _ICO_IN_NAME.sub("", str(out.get("name") or "")).strip(" \n,;")
    return out


def lift_ico_on_record(record: dict) -> dict:
    rec = dict(record)
    if isinstance(rec.get("seller"), dict):
        rec["seller"] = lift_ico_from_party_name(rec["seller"])
    if isinstance(rec.get("buyer"), dict):
        rec["buyer"] = lift_ico_from_party_name(rec["buyer"])
    return rec


def build_sidecar(record: dict, fields: dict) -> dict:
    """Assemble the .extract.json sidecar shape. verified is ALWAYS False at
    extraction time — set here, never left to the caller — because the
    operator-verify rung is a deliberate later act; a field's confidence,
    however high, never auto-passes it (VisionImporter.parse() additionally
    refuses any field under CONFIDENCE_FLOOR regardless of `verified`)."""
    return {"record": record, "fields": fields, "verified": False}


def run_stage_b_stub(ocr_text: str, decode_fn) -> dict:
    """The seam a real Ollama call plugs into: decode_fn(ocr_text, RECORD_SCHEMA)
    -> (record, fields) is expected to POST to the ollama /api/chat endpoint
    with format=RECORD_SCHEMA (native structured output) and return per-field
    logprob confidences. Not wired to a live model here — offline callers pass
    a stub decode_fn. validate_record() still runs on the result, so even a
    stub cannot slip a schema-violating record past this seam."""
    record, fields = decode_fn(ocr_text, RECORD_SCHEMA)
    errors = validate_record(record)
    if errors:
        raise ValueError(f"decode_fn produced a schema-violating record: {errors}")
    return build_sidecar(record, fields)
