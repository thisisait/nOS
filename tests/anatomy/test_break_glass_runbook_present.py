"""Anatomy gate — the break-glass runbook exists and carries its load-bearing
sections.

sso-autologin-plan.md §"Bezpečnost: break-glass + lockout" + §"Testy / gates":

  > **Runbook:** `docs/break-glass-runbook.md` (nový) — sekce: Authentik
  > down/check, container restart, **CLI recovery-key usage**
  > (`docker compose run --rm server create_recovery_key`), per-service
  > fallback truth-table (`ALLOW_LOCAL_LOGIN` vs env-unset+recreate),
  > secrets.yml backup, last-resort. Pinnut `test_break_glass_runbook_present`.

  > `test_break_glass_runbook_present`: `docs/break-glass-runbook.md` existuje,
  > čitelný, má sekce CLI recovery-key/restart/per-service fallback-truth-table.

The break-glass model is load-bearing for enabling autologin at all (Batch 4
"PŘED širokým zapnutím"). This gate fail-fasts if the runbook is missing or has
been gutted of any of its three pinned sections, so the safety doc can't silently
rot away while autologin ships.

The CLI recovery-key procedure is explicitly the canonical escape — verify the
exact `ak create_recovery_key` command is documented (the plan names it
verbatim), not just hand-waved.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNBOOK = REPO / "docs" / "break-glass-runbook.md"


def test_break_glass_runbook_exists_and_readable():
    assert RUNBOOK.is_file(), (
        f"break-glass runbook missing at {RUNBOOK} — the plan "
        f"(§Bezpečnost) requires it before autologin can be enabled."
    )
    text = RUNBOOK.read_text(encoding="utf-8")
    assert text.strip(), "break-glass runbook is empty"


def test_break_glass_runbook_has_cli_recovery_section():
    text = RUNBOOK.read_text(encoding="utf-8")
    low = text.lower()
    # Section heading present.
    assert "cli recovery-key" in low, (
        "runbook missing the 'CLI recovery-key' section heading"
    )
    # The canonical command the plan names verbatim must be documented.
    assert "create_recovery_key" in text, (
        "runbook must document the `create_recovery_key` management command "
        "(the canonical offline Authentik escape)"
    )
    # The A19-form exec command the brief asks for.
    assert "ak create_recovery_key" in text, (
        "runbook must document `ak create_recovery_key <admin>` "
        "(the live A19 container form)"
    )


def test_break_glass_runbook_has_restart_section():
    text = RUNBOOK.read_text(encoding="utf-8")
    low = text.lower()
    assert "container restart" in low, (
        "runbook missing the 'Container restart' section"
    )
    # Authentik down / health-check is the other restart-adjacent section.
    assert "authentik down" in low or "health check" in low, (
        "runbook missing the Authentik down / health-check section"
    )
    assert "docker restart" in low, (
        "runbook restart section must show the actual `docker restart` lever"
    )


def test_break_glass_runbook_has_per_service_fallback_truth_table():
    text = RUNBOOK.read_text(encoding="utf-8")
    low = text.lower()
    assert "truth-table" in low or "truth table" in low, (
        "runbook missing the per-service break-glass truth-table"
    )
    # The two escape kinds the plan distinguishes must both be documented.
    assert "env-unset" in low, (
        "truth-table must document the env-unset + recreate escape kind "
        "(gitea / miniflux — no runtime UI escape)"
    )
    assert "url param" in low or "break-glass param" in low or "break-glass" in low, (
        "truth-table must document the live break-glass URL-param escape kind"
    )
    # The ALLOW_LOCAL_LOGIN fallback pattern the brief names explicitly.
    assert "ALLOW_LOCAL_LOGIN" in text, (
        "runbook must document the ALLOW_LOCAL_LOGIN-style local-login fallback"
    )
    # A representative env-hidden service is named (gitea or miniflux).
    assert "gitea" in low and "miniflux" in low, (
        "truth-table must name the env-hidden services (gitea, miniflux)"
    )


def test_break_glass_runbook_has_secrets_backup_note():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "~/.nos/secrets.yml" in text, (
        "runbook must carry the ~/.nos/secrets.yml backup note "
        "(the offline input for CLI recovery)"
    )
