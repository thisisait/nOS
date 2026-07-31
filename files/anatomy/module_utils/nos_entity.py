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
