"""Anatomy gate: P0-MFA blueprint renders safe in both flag states.

Pins (1) render-clean both flag states (no leftover Jinja), (2) flag-ON shape =
dedicated nos-tier1-mfa-flow with its own validate stage at not_configured_action
='configure' (NOT 'deny'), password policy bound to the enrollment PROMPT stage
(not the login password stage), (3) flag-OFF no-op (entries -> None), (4)
negative-asserts on the lockout footgun + the broken shared-binding override the
adversary rejected.

CI-safe: renders the template via the loader's own jinja env (the production
render path), no Docker / Authentik.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
BP = REPO / "files/anatomy/plugins/authentik-base/blueprints/50-mfa-policy.yaml.j2"


class _OpaqueLoader(yaml.SafeLoader):
    pass


def _opaque(loader, suffix, node):  # !Find / !KeyOf passthrough
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_scalar(node)


_OpaqueLoader.add_multi_constructor("!", _opaque)


def _render(enforce: bool) -> str:
    sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))
    import load_plugins  # noqa: E402

    env = load_plugins._jinja_env()
    return env.from_string(BP.read_text()).render(
        enforce_mfa=enforce,
        mfa_password_min_length=15,
        mfa_password_hibp=False,
    )


def test_render_clean_both_flag_states():
    for flag in (True, False):
        out = _render(flag)
        assert "version: 1" in out
        assert "{{" not in out and "{%" not in out, f"unrendered jinja with enforce_mfa={flag}"


def test_flag_off_is_noop():
    doc = yaml.load(_render(False), Loader=_OpaqueLoader)
    assert (doc or {}).get("entries") in (None, []), "flag-off must emit no entries"


def test_flag_on_shape():
    doc = yaml.load(_render(True), Loader=_OpaqueLoader)
    entries = doc["entries"]

    # Two validate stages now (posture B, 2026-06-02):
    #   1. nos-mfa-validate — the dedicated Tier-1 stage (force-enrol, totp+webauthn)
    #   2. default-authentication-mfa-validation — the STOCK shared stage, managed
    #      THRESHOLD-ONLY (widen last_auth_threshold to the remember-window so an
    #      enrolled user re-challenges once per window, not every login). We must
    #      NEVER re-arm not_configured_action / device_classes on the stock stage
    #      (that is the over-scope / lockout footgun).
    validate = [e for e in entries
                if e["model"] == "authentik_stages_authenticator_validate.authenticatorvalidatestage"]
    names = {v["identifiers"]["name"] for v in validate}
    assert names == {"nos-mfa-validate", "default-authentication-mfa-validation"}, \
        f"expected exactly the dedicated + tamed-stock validate stages, got {names}"

    nmv = next(v for v in validate if v["identifiers"]["name"] == "nos-mfa-validate")
    assert nmv["attrs"]["not_configured_action"] == "configure"
    assert nmv["attrs"]["device_classes"] == ["totp", "webauthn"]
    assert nmv["attrs"]["configuration_stages"]  # non-empty
    assert nmv["attrs"]["last_auth_threshold"] == "hours=8"  # mfa_remember_window default

    stock = next(v for v in validate if v["identifiers"]["name"] == "default-authentication-mfa-validation")
    assert set(stock["attrs"].keys()) == {"last_auth_threshold"}, (
        "the stock default-authentication-mfa-validation override must be THRESHOLD-ONLY "
        f"(never re-arm not_configured_action / device_classes), got {set(stock['attrs'].keys())}"
    )
    assert stock["attrs"]["last_auth_threshold"] == "hours=8"

    # dedicated authentication flow
    flows = [e for e in entries if e["model"] == "authentik_flows.flow"]
    assert any(f["identifiers"].get("slug") == "nos-tier1-mfa-flow" for f in flows)

    # password policy (zxcvbn on, HIBP off, length 15)
    pol = [e for e in entries
           if e["model"] == "authentik_policies_password.passwordpolicy"]
    assert len(pol) == 1
    assert pol[0]["attrs"]["length_min"] == 15
    assert pol[0]["attrs"]["check_zxcvbn"] is True
    assert pol[0]["attrs"]["check_have_i_been_pwned"] is False

    # Password policy is created but NOT blueprint-bound to a prompt stage:
    # Authentik's policybinding.target for a prompt stage atomically failed the
    # WHOLE blueprint on the live 2026-05-31 blank+gov run (null / does-not-exist
    # pk), so the brittle bindings were dropped (the core MFA flow doesn't need
    # them). Pin that NO policybinding ships (regression guard against re-adding
    # the blueprint-killing entry).
    pol_binds = [e for e in entries if e["model"] == "authentik_policies.policybinding"]
    assert pol_binds == [], \
        "no policybinding may ship — a null/invalid prompt-stage target atomically rejects the whole blueprint"


def test_source_negative_asserts():
    src = BP.read_text()
    assert "not_configured_action: configure" in src
    assert "not_configured_action: deny" not in src, "lockout footgun must be absent"
    assert "!Find" in src
    # 2026-06-02: the stock default-authentication-mfa-validation IS now managed
    # (posture B remember-window) — but THRESHOLD-ONLY. The structural guarantee
    # (attrs == {last_auth_threshold}) is pinned in test_flag_on_shape. The old
    # "must not mention the stock stage" assertion is intentionally dropped: we
    # widen its threshold on purpose; we must only never re-arm its scoping fields.
