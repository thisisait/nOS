"""Anatomy gate — Portainer admin-password DRIFT self-heal.

Portainer's admin password can only be rotated via the API WITH the old password.
When an interrupted/partial provisioning (e.g. an aborted blank) leaves the admin
with a password that is neither the current nor the previous prefix, the reconverge
is stuck → OAuth/SSO config is skipped → the loud SSO verify FAILS the run (true
positive, live 2026-06-15). Portainer holds no user data, so the robust heal is to
wipe its BoltDB and let admin-init recreate the admin with the config password.

This gate pins: drift is detected, healed only behind the OPT-IN flag (manual-over-
auto), the off-path is a LOUD actionable diagnostic (no silent dead-SSO), and the
flag carries a real default in default.config.yml (which loads before core-up, so
the {{ vars }} eager-finalize trap can't abort the run on it).
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
POST = (REPO / "roles/pazny.portainer/tasks/post.yml").read_text(encoding="utf-8")
CONFIG = (REPO / "default.config.yml").read_text(encoding="utf-8")


def test_drift_is_detected_from_both_failed_logins():
    assert "_portainer_pw_drift" in POST, "drift must be computed into a fact"
    seg = POST[POST.find("Detect admin-password DRIFT"):POST.find("Auto-heal admin DRIFT")]
    # admin exists AND current prefix failed AND previous prefix failed.
    assert "_portainer_admin_check.status | default(0) == 204" in seg
    assert "_portainer_auth_new.status | default(0) != 200" in seg
    assert "_portainer_auth_old.status | default(0) != 200" in seg


def test_heal_is_opt_in_only():
    seg = POST[POST.find("Auto-heal admin DRIFT"):POST.find("DRIFT but auto-reset OFF")]
    assert "portainer_admin_auto_reset | default(false) | bool" in seg, \
        "the destructive BoltDB wipe must be gated behind the opt-in flag"
    assert "_portainer_pw_drift | default(false) | bool" in seg, \
        "heal must only run when drift was actually detected"


def test_heal_wipes_bolt_db_then_reinits_with_config_password():
    seg = POST[POST.find("Auto-heal admin DRIFT"):POST.find("DRIFT but auto-reset OFF")]
    assert "{{ portainer_data_dir }}/portainer.db" in seg and "state: absent" in seg, \
        "heal must remove the BoltDB (the admin store)"
    assert "/api/users/admin/init" in seg, "heal must re-init the admin after the wipe"
    assert "portainer_admin_password | default" in seg, "re-init must use the config password"
    # ordering: stop → wipe → start → wait → re-init
    assert seg.find("stop infra-portainer-1") < seg.find("portainer.db") < seg.find("start infra-portainer-1") < seg.find("admin/init"), \
        "heal order must be stop → wipe → start → re-init"


def test_off_path_is_a_loud_actionable_diagnostic():
    # No silent dead-SSO: when auto-reset is off, the drift must surface a paste-able
    # heal path (not a vague 'manual reset required' that hides the fix).
    seg = POST[POST.find("DRIFT but auto-reset OFF"):POST.find("Get auth token for admin")]
    assert "portainer_admin_auto_reset=true" in seg, "diagnostic must name the opt-in flag"
    assert "portainer.db" in seg and "stop infra-portainer-1" in seg, \
        "diagnostic must give the manual heal commands"
    assert "not (portainer_admin_auto_reset | default(false) | bool)" in seg, \
        "diagnostic shows only when auto-reset is OFF"


def test_flag_has_real_default_before_core_up():
    # Portainer post runs in core-up; the flag must have a real default in
    # default.config.yml (a role default would be too late — the {{ vars }} trap).
    assert "portainer_admin_auto_reset: false" in CONFIG, \
        "portainer_admin_auto_reset must default in default.config.yml (loads before core-up)"


def test_idempotent_when_sso_already_active():
    # Once OAuth2 is active (AuthenticationMethod==3) Portainer's internal admin
    # login 422s by design, so the password machinery is MOOT. A re-converge must
    # NOT raise a false DRIFT and must NOT retry the OAuth config — else every run
    # alarms even though SSO is fine. Pinned: read AuthMethod from the unauth public
    # endpoint, exclude ==3 from drift, gate the OAuth-config JWT fetch on != 3.
    assert "/api/settings/public" in POST and "_portainer_authmethod" in POST, \
        "post.yml must read AuthenticationMethod from the unauth public endpoint"
    drift = POST[POST.find("Detect admin-password DRIFT"):POST.find("Auto-heal admin DRIFT")]
    assert "_portainer_authmethod | default(0) | int != 3" in drift, \
        "drift must be FALSE when SSO is already active (==3) — no false alarm"
    jwt = POST[POST.find("Get auth token for admin"):POST.find("SSO already active")]
    assert "_portainer_authmethod | default(0) | int != 3" in jwt, \
        "the OAuth-config JWT fetch must be skipped when SSO is already active (idempotent)"
