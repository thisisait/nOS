"""Anatomy gate: role-level restart handlers must fail loud.

A handler runs at the END of a play, AFTER all tasks have mutated config
on disk. A masked restart failure (`failed_when: false`) therefore leaves
the system in an INCONSISTENT state — new config written, old container
still running — with NO diagnostic and a green playbook. This is the exact
class of bug A17 (2026-05-20) fixed for the Wing daemon handler after a
silent bootstrap failure left wing.pazny.eu 502 despite a green run.

The fleet-wide audit (feat/v0.7-overnight) found 49 pure
``{{ docker_bin }} compose ... restart <svc>`` role handlers carrying a
blanket ``failed_when: false`` — every one of them silently swallowed a
failed restart. The fix is mechanical: drop the flag so a failed restart
fails the play.

DOCTRINE (this gate pins it):
  * A pure docker-compose-restart role handler MUST NOT carry
    ``failed_when: false``. If a service can legitimately be absent
    mid-play, gate it with a SMART conditional (register + a guarded
    ``failed_when:`` that only tolerates the specific expected stderr,
    like ``roles/pazny.smtp_stalwart`` already does), never a blanket mask.

ALLOWLIST — the only role handlers permitted to keep ``failed_when: false``
are those whose restart wraps a step that legitimately exits non-zero
(launchctl bootout on a not-yet-loaded label, a `|| true`-guarded blueprint
re-apply loop, an sshd reload whose unit name differs across distros). These
are best-effort by construction, not silent-failure masking. New entries
require a documented justification here.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
HANDLERS = sorted(REPO.glob("roles/*/handlers/main.yml"))

# Roles whose handler contains a step that legitimately exits non-zero.
# Each MUST carry a real justification — do not add a plain docker-restart
# handler here to dodge the gate.
ALLOWLISTED = {
    # launchctl bootout (not-yet-loaded label) → expected non-zero; the
    # docker `restart traefik`/`restart nginx` steps are `when:`-gated
    # best-effort cert-bounce, not the silent-restart-failure pattern.
    "pazny.acme": "launchctl bootout of an unloaded label expects rc!=0",
    # `ak apply_blueprint` loop already `|| true`s each blueprint internally;
    # the outer failed_when mirrors the play-level handler in main.yml.
    "pazny.authentik": "blueprint re-apply loop is `|| true`-guarded per-bp",
    # launchctl unload of an unloaded plist expects rc!=0 before load -w.
    "pazny.backup": "launchctl unload before load expects rc!=0",
    # launchctl bootout before bootstrap expects rc!=0 (role-local twin of
    # the play-level openclaw handler, which takes priority anyway).
    "pazny.openclaw": "launchctl bootout before bootstrap expects rc!=0",
    # sshd unit name differs across distros (ssh.service vs sshd.service).
    "pazny.linux.hardening": "sshd unit name varies across distros",
}


def _role(path: pathlib.Path) -> str:
    return path.parts[-3]


def test_pure_docker_restart_handlers_fail_loud():
    """No pure docker-compose-restart role handler may mask restart failures."""
    offenders = []
    for h in HANDLERS:
        role = _role(h)
        if role in ALLOWLISTED:
            continue
        text = h.read_text()
        if "failed_when: false" in text:
            offenders.append(role)
    assert not offenders, (
        "These role handlers still mask restart failures with "
        "`failed_when: false` — a failed restart at end-of-play leaves "
        "config-on-disk / old-container drift with no diagnostic. Remove the "
        "flag (or use a SMART register+failed_when like pazny.smtp_stalwart): "
        + ", ".join(sorted(offenders))
    )


def test_named_bug_handlers_are_clean():
    """The handlers named in the bug report must be fail-loud now."""
    for role in (
        "pazny.prometheus",
        "pazny.calibre_web",
        "pazny.ntfy",
        "pazny.qgis_server",
    ):
        text = (REPO / "roles" / role / "handlers" / "main.yml").read_text()
        assert "failed_when: false" not in text, (
            f"{role} handler must not carry failed_when: false (named in the "
            "handlers-silent-restart-failure bug report)"
        )


def test_allowlisted_handlers_still_exist():
    """Guard against a stale allowlist: every allowlisted role must exist and
    still carry failed_when: false (else drop it from the allowlist)."""
    for role in ALLOWLISTED:
        h = REPO / "roles" / role / "handlers" / "main.yml"
        assert h.exists(), f"allowlisted role {role} has no handler file"
        assert "failed_when: false" in h.read_text(), (
            f"{role} no longer carries failed_when: false — remove it from "
            "the ALLOWLISTED map so the allowlist doesn't rot"
        )


def test_allowlist_justifications_present():
    """Every allowlist entry must carry a non-empty justification string."""
    for role, reason in ALLOWLISTED.items():
        assert reason and reason.strip(), f"{role} allowlist entry needs a reason"


def test_smtp_stalwart_uses_smart_conditional():
    """The canonical 'best-effort done right' example: a guarded failed_when,
    NOT a blanket false. Pins the pattern future handlers should copy."""
    h = REPO / "roles" / "pazny.smtp_stalwart" / "handlers" / "main.yml"
    text = h.read_text()
    assert "failed_when: false" not in text
    assert "register:" in text
    assert "No such service" in text, (
        "smtp_stalwart must tolerate only the specific 'No such service' "
        "stderr, not all failures"
    )
