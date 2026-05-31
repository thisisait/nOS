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

    # dedicated validate stage named nos-mfa-validate (NOT an override of the
    # shared upstream default-authentication-mfa-validation)
    validate = [e for e in entries
                if e["model"] == "authentik_stages_authenticator_validate.authenticatorvalidatestage"]
    assert len(validate) == 1
    assert validate[0]["identifiers"]["name"] == "nos-mfa-validate"
    assert validate[0]["attrs"]["not_configured_action"] == "configure"
    assert validate[0]["attrs"]["device_classes"] == ["totp", "webauthn"]
    assert validate[0]["attrs"]["configuration_stages"]  # non-empty

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

    # password policy bound to the enrollment PROMPT stage (not login pw stage)
    pol_binds = [e for e in entries if e["model"] == "authentik_policies.policybinding"]
    targets = [str(b["identifiers"].get("target")) for b in pol_binds]
    assert any("nos-enrollment-prompts" in t for t in targets), \
        "password policy must bind the enrollment prompt stage"
    assert not any("default-authentication-password" in t for t in targets), \
        "password policy must NOT bind the login password stage (would be inert)"


def test_source_negative_asserts():
    src = BP.read_text()
    assert "not_configured_action: configure" in src
    assert "not_configured_action: deny" not in src, "lockout footgun must be absent"
    assert "default-authentication-mfa-validation" not in src, \
        "must not override the shared upstream validate stage (broken scoping)"
    assert "!Find" in src
