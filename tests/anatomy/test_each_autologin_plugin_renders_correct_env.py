"""Anatomy gate — each supports:yes autologin plugin renders the documented
force-OIDC env behind the autologin gate.

sso-autologin-plan.md §"Testy / gates":

  > `test_each_autologin_plugin_renders_correct_env`: loader pre_compose
  > render každého autologin pluginu obsahuje force-OIDC env (env reálně
  > dorazí do kontejneru).

For every plugin whose `authentik.autologin.supports == "yes"`, the
service's compose-extension template (the env-driven force-OIDC path) MUST
carry the documented force-OIDC env var, conditioned on the autologin
enable chain (`{% if (... | bool) %}`). The exact tokens come from the
plan's per-service matrix and were adversarially verified — e.g. Grafana
uses `GF_AUTH_OAUTH_AUTO_LOGIN` (under the `[auth]` section), NOT the
non-existent `GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN`.

Batch 0 reality: NO plugin declares `autologin.supports: yes` yet, so the
iteration is empty and this gate passes VACUOUSLY. It starts asserting the
moment Grafana (Batch 1) lands its autologin block + compose-extension env.

Render strategy: the documented fallback from the Batch-0 brief — assert on
the presence of the documented env token AND a gating `{% if %}` block in
the compose-extension template source. A full loader render harness is
heavier than needed to pin "the env token exists, gated"; the source check
is the load-bearing contract (the env reaches the container only if the
token is present and gated). Config-hook services (occ / config.py / yaml /
API) are exempt from the env-source check — they gate a task/template, not
compose env — and are skipped here (their gates live in their own batch).
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = REPO / "files" / "anatomy" / "plugins"

# Documented force-OIDC env token per env-driven service (plan matrix (a)/(b)).
# Config-hook services (nextcloud/superset/homeassistant/portainer-API) are
# NOT in this map — they don't render env, so they're not env-source-checked.
# Adversarially-verified tokens (the plan is authoritative over memory).
DOCUMENTED_FORCE_OIDC_ENV = {
    "grafana-base": "GF_AUTH_OAUTH_AUTO_LOGIN",   # under [auth], NOT _GENERIC_OAUTH_
    "bookstack-base": "AUTH_AUTO_INITIATE",
    "wordpress-base": "WP_OIDC_LOGIN_TYPE",
    "freescout-base": "OAUTHLOGIN_FORCE_OAUTH_LOGIN",
    "gitea-base": "ENABLE_PASSWORD_SIGNIN_FORM",
    "gitlab-base": "omniauth_auto_sign_in_with_provider",
    "miniflux-base": "DISABLE_LOCAL_AUTH",
    "vaultwarden-base": "SSO_ONLY",
}


def _supports_yes_plugins() -> list[tuple[str, dict, pathlib.Path]]:
    out: list[tuple[str, dict, pathlib.Path]] = []
    for p in sorted(PLUGINS.glob("*/plugin.yml")):
        data = yaml.safe_load(p.read_text())
        a = (data or {}).get("authentik")
        if not isinstance(a, dict):
            continue
        al = a.get("autologin")
        if isinstance(al, dict) and al.get("supports") == "yes":
            out.append((p.parent.name, data, p))
    return out


def test_each_autologin_plugin_renders_correct_env():
    plugins = _supports_yes_plugins()
    if not plugins:
        pytest.skip(
            "Batch 0: no plugin declares autologin.supports: yes yet — "
            "this gate starts asserting once Grafana (Batch 1) lands.")

    failures: list[str] = []
    for name, manifest, plugin_path in plugins:
        token = DOCUMENTED_FORCE_OIDC_ENV.get(name)
        if token is None:
            # Config-hook (occ/config.py/yaml/API) service: not env-driven.
            # Its force-OIDC gate is verified by that service's own batch gate.
            continue
        ce = manifest.get("compose_extension") or {}
        tmpl_rel = ce.get("template")
        if not tmpl_rel:
            failures.append(f"{name}: supports:yes but no compose_extension.template")
            continue
        tmpl = plugin_path.parent / tmpl_rel
        if not tmpl.exists():
            failures.append(f"{name}: compose-extension template missing at {tmpl}")
            continue
        src = tmpl.read_text()
        if token not in src:
            failures.append(
                f"{name}: documented force-OIDC env {token!r} absent from "
                f"compose-extension template")
        elif "{% if" not in src:
            failures.append(
                f"{name}: force-OIDC env {token!r} present but not behind a "
                f"`{{% if %}}` autologin gate (would always render)")
    assert not failures, (
        "supports:yes autologin plugins not rendering the documented "
        "force-OIDC env behind the autologin gate:\n"
        + "\n".join(f"  {f}" for f in failures))
