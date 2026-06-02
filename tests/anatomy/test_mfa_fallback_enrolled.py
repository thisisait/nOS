"""Anatomy gate (P0-1) — admin MFA break-glass fallback task is correctly gated.

tasks/authentik-mfa-bootstrap.yml seeds a StaticDevice (typed break-glass codes)
for ONE nos-admins identity ONLY when it has no non-passkey factor yet
(totp==0 AND static==0). This guards against the passkey-only lockout that
enforce_mfa's force-enrolment can create (the operator's symptom #1, 2026-06-02).

Pins: (1) main.yml imports it gated on install_authentik AND enforce_mfa (a no-op
with MFA off); (2) it seeds ONLY on the no-fallback condition; (3) it is never
destructive (no delete/rotate of an existing device); (4) the codes are no_log.

CI-safe: source-scan only; no Docker / Authentik.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
TASK = REPO / "tasks/authentik-mfa-bootstrap.yml"
MAIN = REPO / "main.yml"


def test_task_exists():
    assert TASK.is_file(), "tasks/authentik-mfa-bootstrap.yml must exist (P0-1 break-glass fallback)"


def test_seeds_only_when_no_fallback():
    src = TASK.read_text()
    assert "if static > 0 or totp > 0" in src, (
        "must skip seeding when the admin already has a totp/static fallback"
    )
    assert "StaticDevice.objects.create" in src, "must create a StaticDevice break-glass device"


def test_never_destructive():
    src = TASK.read_text()
    assert ".delete(" not in src, "the bootstrap task must never delete an existing device/token"


def test_codes_are_no_log():
    src = TASK.read_text()
    assert src.count("no_log: true") >= 2, "the seed + persist tasks must both be no_log (codes are secrets)"


def test_import_gated_on_authentik_and_enforce_mfa():
    src = MAIN.read_text()
    assert "tasks/authentik-mfa-bootstrap.yml" in src, "main.yml must import the bootstrap task"
    idx = src.index("tasks/authentik-mfa-bootstrap.yml")
    block = src[idx: idx + 500]
    assert "install_authentik" in block, "import must be gated on install_authentik"
    assert "enforce_mfa" in block, "import must be gated on enforce_mfa (no-op with MFA off)"
