"""Anatomy gate — infisical autologin is SEED-ONLY in OSS (no enforce).

sso-autologin-plan.md §"Per-service matice (d)" + §"Testy / gates":

  > infisical: OIDC enforce je enterprise-gated; OSS bez auto-redirectu.
  > partial seed; enforce deferován. Gate `test_infisical_no_enforce_in_oss`
  > ověří, že plugin nerenderuje enterprise-only enforce volání v OSS módu.

Honesty contract for Infisical CE (OSS):
  - The OIDC_* env seeds a "Sign in with Authentik" BUTTON. That is the whole
    OSS capability.
  - "Enforce OIDC" / pre-login auto-redirect / forced OIDC-only login is an
    ENTERPRISE feature — there is NO OSS env var or API that forces it.
  - `authentik.autologin.supports` is therefore "partial", and turning
    autologin on (sso_autologin=true) must STILL only seed the button: the
    compose-extension may render a benign marker, but it must NEVER render an
    enterprise enforce env/API call that would silently no-op (or, worse,
    half-configure) on an OSS build.

This gate renders the infisical compose-extension with autologin forced ON
(every override truthy) through the SAME path the loader uses, and asserts no
enterprise enforce token reaches the rendered (non-comment) compose env. It
also asserts the plugin declares no post-API enforce hook. Comment lines (which
legitimately explain WHY enforce is deferred) are stripped before the scan, so
the honest documentation can keep the word "enforce" without tripping the gate.
"""

from __future__ import annotations

import pathlib
import re

import yaml

# tests/conftest.py adds files/anatomy/ to sys.path.
from module_utils import load_plugins  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO / "files" / "anatomy" / "plugins" / "infisical-base"
PLUGIN_YML = PLUGIN_DIR / "plugin.yml"
COMPOSE_EXT = PLUGIN_DIR / "templates" / "infisical-base.compose.yml.j2"

# Enterprise-only "enforce OIDC" tokens that must NEVER reach an OSS render.
# Infisical's enterprise enforce surface is the org-setting `authEnforced`
# (PATCH /api/v1/organizations/<id>) plus any *_ENFORCE / ENFORCE_* /
# *_OIDC_ENFORCE / *_FORCE_SSO style env. Match case-insensitively on the
# rendered env keys / API field names — NOT on prose.
_ENFORCE_TOKENS = (
    "authenforced",
    "oidc_enforce",
    "enforce_oidc",
    "enforce_sso",
    "sso_enforced",
    "force_sso",
    "saml_enforced",
)

# Minimal var scope that forces the autologin gate ON (worst case for OSS).
_FORCE_ON_CTX = {
    "install_authentik": True,
    "sso_autologin": True,
    "sso_autologin_infisical": True,
    "sso_autologin_min_tier_1": True,
    "global_password_prefix": "nos",
    "tenant_domain": "dev.local",
    "infisical_domain": "vault.dev.local",
    "infisical_port": 8080,
}


def _strip_jinja_and_yaml_comments(line: str) -> str:
    """Drop `# ...` comments (both YAML and the rendered prose) and `{# #}`."""
    line = re.sub(r"\{#.*?#\}", "", line)
    hash_idx = line.find("#")
    if hash_idx != -1:
        line = line[:hash_idx]
    return line


def _render_compose_ext_force_on() -> str:
    """Render the infisical compose-extension with autologin forced ON,
    then strip comments so the scan only sees real compose env/keys."""
    src = COMPOSE_EXT.read_text()
    rendered = load_plugins._render_string(src, dict(_FORCE_ON_CTX))
    kept = [_strip_jinja_and_yaml_comments(ln) for ln in rendered.splitlines()]
    return "\n".join(kept)


def test_infisical_autologin_is_partial_seed_only():
    """The honesty verdict itself: supports must be 'partial', never 'yes'
    (claiming 'yes' would promise an OSS enforce that does not exist)."""
    data = yaml.safe_load(PLUGIN_YML.read_text())
    al = ((data or {}).get("authentik") or {}).get("autologin") or {}
    assert al, "infisical plugin lost its authentik.autologin block"
    assert al.get("supports") == "partial", (
        "infisical autologin.supports must be 'partial' (OSS = button seed "
        f"only, enforce enterprise-gated); got {al.get('supports')!r}")
    # OSS cannot hide the form — claiming hides_local_form:true would be a lie.
    assert al.get("hides_local_form") in (False, None), (
        "infisical OSS cannot hide/enforce the local form; hides_local_form "
        f"must be false, got {al.get('hides_local_form')!r}")


def test_infisical_no_enforce_in_oss():
    """With autologin forced ON, the rendered OSS compose-extension must carry
    NO enterprise enforce env/API token — only the benign button seed."""
    rendered = _render_compose_ext_force_on().lower()
    hits = [tok for tok in _ENFORCE_TOKENS if tok in rendered]
    assert not hits, (
        "infisical compose-extension rendered an ENTERPRISE-only enforce token "
        f"in OSS mode (autologin forced on): {hits}. Enforce OIDC is "
        "enterprise-gated — OSS must seed the button only, never an enforce "
        "env/API call.")


def test_infisical_no_post_api_enforce_hook():
    """The plugin must not wire a post-compose API call that enforces OIDC —
    that would attempt the enterprise org-setting (authEnforced) on OSS."""
    data = yaml.safe_load(PLUGIN_YML.read_text())
    lifecycle = (data or {}).get("lifecycle") or {}
    # Flatten every lifecycle step token to plain text for the scan.
    text = yaml.safe_dump(lifecycle).lower()
    hits = [tok for tok in _ENFORCE_TOKENS if tok in text]
    assert not hits, (
        "infisical lifecycle declares an enforce-OIDC hook "
        f"({hits}); enforce is enterprise-gated and must be deferred, not "
        "wired into a post-compose API call.")
