"""Anatomy gate — Uptime Kuma single sign-in (no double login behind forward_auth).

Kuma v1 has no OIDC; behind the Authentik forward_auth gate its OWN login is a
pointless second sign-in (the operator's "kuma still asks for a password after
Authentik" wart). The role disables Kuma's internal login (disableAuth=true) so
the embedded outpost is the only sign-in. Pinned here:
  - the disable runs gated on install_authentik (never leave Kuma open without
    the gate) + an opt-out flag, and is idempotent (skips when already disabled);
  - it runs AFTER the API-login monitor setup, and that setup SKIPS when auth is
    already off (its login() would fail) — so monitor auto-setup isn't broken;
  - the flag defaults true in the role.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
MON = (REPO / "roles/pazny.uptime_kuma/tasks/monitors.yml").read_text(encoding="utf-8")
DEF = (REPO / "roles/pazny.uptime_kuma/defaults/main.yml").read_text(encoding="utf-8")


def test_disable_task_exists_and_is_gated():
    seg = MON[MON.find("Disable internal login"):]
    assert seg, "monitors.yml must have the disable-internal-login task"
    assert "install_authentik | default(false)" in seg, \
        "disable must be gated on install_authentik — never open Kuma without the gate"
    assert "uptime_kuma_disable_internal_auth | default(true)" in seg, \
        "disable must honour the opt-out flag"
    assert "not (_kuma_auth_disabled | default(false))" in seg, \
        "disable must be idempotent — skip when already disabled (no churn/bounce)"
    assert "disableAuth" in seg and "INSERT INTO setting" in seg, \
        "disable must set disableAuth=true in Kuma's setting table"


def test_disable_runs_after_monitor_setup():
    # The disable must come AFTER the monitor auto-setup so the API-login setup
    # ran with auth still on (fresh blank).
    setup = MON.find("Auto-create monitors")
    disable = MON.find("Disable internal login")
    assert setup != -1 and disable != -1 and setup < disable, \
        "monitor setup must run before auth is disabled (its login needs auth on)"


def test_setup_skips_when_auth_already_off():
    # On a re-converge auth is already off; the password reconverge + monitor
    # setup must skip (their login() would fail and burn the retry budget).
    assert MON.count("not (_kuma_auth_disabled | default(false))") >= 3, \
        "reconverge + monitor-setup + the disable task must all key off _kuma_auth_disabled"
    assert "Read current disableAuth setting" in MON, \
        "auth-disabled state must be read early to gate the login-based tasks"


def test_flag_defaults_true():
    assert "uptime_kuma_disable_internal_auth: true" in DEF, \
        "single-login must default on (it only applies when install_authentik anyway)"
