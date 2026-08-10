"""GENERATED — do not edit. Source: state/genome/entity.schema.json (via tools/genome-codegen.py).

Consumers: the plugin loader and apps_runner. Editing this file by hand makes
the `contracts-drift` CI job go red, which is the point.
"""
from __future__ import annotations

import re

LEGAL_BASIS = (
    "consent",
    "contract",
    "legal_obligation",
    "vital_interests",
    "public_task",
    "legitimate_interests",
)

ACCESS_GATES = (
    "none",
    "forward_auth",
    "oidc",
    "header_oidc",
)

FACE_SURFACES = (
    "window",
    "panel",
    "embed",
    "hidden",
)

#: The adjective axes. A fourth one is a genome edit, not a fifth file.
AXES = (
    "form",
    "build",
    "layer",
)

APP_FORMS = (
    "view",
    "utility",
    "widget",
    "frame",
)

APP_BUILDS = (
    "F1",
    "F2",
    "F3",
    "F4",
    "H",
)

#: The layers a service can be PLACED at. `None` is legal on an entity and is
#: deliberately absent here: it is the refusal to place, not a fifth layer.
SERVICE_LAYERS = (
    "L0",
    "L1",
    "L2",
    "L3",
)

#: Vocabulary per axis, so a consumer validates by axis NAME and a new axis
#: reaches every consumer without one of them being edited to notice.
AXIS_VOCABULARY = {
    "form": APP_FORMS,
    "build": APP_BUILDS,
    "layer": SERVICE_LAYERS,
}

#: LLM providers that have an adapter. The enum ships SECOND — see the genome's
#: `llm.provider` note: a member here with no adapter is validation outrunning
#: capability.
LLM_PROVIDERS = (
    "anthropic",
    "openclaw",
)

#: `<provider>-<the vendor's own model id>`. DERIVED from LLM_PROVIDERS, so the
#: list cannot be restated. The tail carries colons on purpose: every real
#: ollama tag has one, and a spelling that cannot express the right value gets
#: approximated into a wrong one.
MODEL_URI_PATTERN = r"^(anthropic|openclaw)-[A-Za-z0-9._:/-]{1,96}$"
MODEL_URI_RE = re.compile(MODEL_URI_PATTERN)

ANCHOR_PATTERN = r"^[0-9]{2}(\.[0-9]{2}){0,2}$"
ANCHOR_RE = re.compile(ANCHOR_PATTERN)

LAYER_WITHHELD_MIN_LENGTH = 40

IDENTITY_REQUIRED = (
    "name",
    "version",
    "description",
    "kind",
)

COMPLIANCE_REQUIRED = (
    "purpose",
    "legal_basis",
    "data_categories",
    "data_subjects",
    "retention_days",
    "processors",
)

ACCESS_REQUIRED = (
    "routed",
    "gate",
)

ENTITY_REQUIRED = (
    "identity",
    "compliance",
)

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}[a-z0-9]$")

JUSTIFICATION_MIN_LENGTH = 40
TIER_MIN = 1
TIER_MAX = 4


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


def withheld_layer_needs_a_reason(axes: dict) -> bool:
    """True when a layer was withheld and the withholding is silent.

    The absence twin of ungated_route_needs_justification, and the reason the
    `layer` axis is worth having: 38 of 63 services carry no layer today, so a
    null that rendered as a default would say "application leaf" about a
    service nobody has read. JSON Schema states this too (axes.allOf); it is
    restated here because the anatomy compiler stamps the field before any
    validator sees it, and the refusal has to happen at the stamp.
    """
    if "layer" not in axes or axes["layer"] is not None:
        return False
    return len((axes.get("layer_withheld") or "").strip()) < LAYER_WITHHELD_MIN_LENGTH


def axis_value_is_declared(axis: str, value) -> bool:
    """False when `value` is outside the genome's vocabulary for `axis`.

    Until 2026-08-07 nothing anywhere ran this check: the face declared the two
    app vocabularies in TypeScript, the anatomy compiler read the same registry
    with a regex and accepted whatever string it found, so `form: 'veiw'`
    became a fourth form in the estate's address space in silence.
    """
    if axis not in AXIS_VOCABULARY:
        return False
    if axis == "layer" and value is None:
        return True   # a withholding, checked by withheld_layer_needs_a_reason
    return value in AXIS_VOCABULARY[axis]
