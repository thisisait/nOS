"""Anatomy gate — local-login fallback (break-glass layer 2) renders an
`ALLOW_LOCAL_LOGIN`-style env behind the per-service toggle, when wired.

sso-autologin-plan.md §"Bezpečnost: break-glass + lockout" point 2 +
§"Testy / gates":

  > **Per-service local-login toggle.** `enable_<svc>_local_login: true` v
  > `default.config.yml` → compose-extension renderuje
  > `ALLOW_LOCAL_LOGIN`/ekvivalent. Default `false` (pure-SSO). Pinnut
  > `test_local_login_fallback_renders_when_enabled`.

  > `test_local_login_fallback_renders_when_enabled`: pro `autologin:true`
  > službu s `enable_<svc>_local_login:true` compose-extension podmíněně
  > renderuje `ALLOW_LOCAL_LOGIN`.

The contract (plan §contract lines 52–53) carries an optional
`autologin.local_login_fallback` field:

    autologin:
      local_login_fallback: "{{ enable_<svc>_local_login | default(false) | bool }}"

and, where adopted, the compose-extension renders the bypass env behind a
matching `{% if enable_<svc>_local_login ... %}` gate:

    {% if enable_<svc>_local_login | default(false) | bool %}
          ALLOW_LOCAL_LOGIN: "true"
    {% endif %}

TOLERANT BY DESIGN (per the Batch-4 brief): NO service wires this env yet — it
is a documented pattern, not a live wiring (Batch 4 wires the mechanism + docs,
not the per-service env). So:

  * If no plugin declares `autologin.local_login_fallback`, this gate SKIPS
    (vacuous — there is nothing to render). The pattern is documented in
    docs/break-glass-runbook.md §"Local-login fallback".
  * Once a service adopts the pattern, the gate asserts its compose-extension
    actually renders an ALLOW_LOCAL_LOGIN-style env behind a `{% if %}` gate
    keyed on the per-service toggle (so the env reaches the container only when
    the operator opts in).
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = REPO / "files" / "anatomy" / "plugins"

# Recognised local-login bypass env tokens (service-equivalents of the
# canonical ALLOW_LOCAL_LOGIN). Extend as services adopt the pattern.
LOCAL_LOGIN_ENV_TOKENS = (
    "ALLOW_LOCAL_LOGIN",
    "DISABLE_LOGIN_FORM",   # grafana-style: rendering it false-y = local form stays
    "ENABLE_PASSWORD_SIGNIN_FORM",  # gitea-style local-form env
    "SSO_ONLY",             # vaultwarden-style: false = master-password stays
    "DISABLE_LOCAL_AUTH",   # miniflux-style: unset = local form stays
)


def _plugins_with_local_login_fallback() -> list[tuple[str, dict, pathlib.Path]]:
    """Plugins whose autologin block declares a `local_login_fallback`."""
    out: list[tuple[str, dict, pathlib.Path]] = []
    for p in sorted(PLUGINS.glob("*/plugin.yml")):
        data = yaml.safe_load(p.read_text())
        a = (data or {}).get("authentik")
        if not isinstance(a, dict):
            continue
        al = a.get("autologin")
        if isinstance(al, dict) and "local_login_fallback" in al:
            out.append((p.parent.name, data, p))
    return out


def _compose_ext_template(manifest: dict, plugin_dir: pathlib.Path) -> pathlib.Path | None:
    ce = manifest.get("compose_extension") or {}
    rel = ce.get("template")
    if not rel:
        return None
    return plugin_dir / rel


def test_local_login_fallback_renders_when_enabled():
    plugins = _plugins_with_local_login_fallback()
    if not plugins:
        pytest.skip(
            "No plugin declares autologin.local_login_fallback yet — the "
            "ALLOW_LOCAL_LOGIN-style fallback is a documented pattern "
            "(docs/break-glass-runbook.md §'Local-login fallback'), not a "
            "live wiring. This gate starts asserting once a service adopts it."
        )

    failures: list[str] = []
    for name, manifest, plugin_path in plugins:
        a = manifest["authentik"]
        slug = a.get("slug") or name.removesuffix("-base")
        tmpl = _compose_ext_template(manifest, plugin_path.parent)
        if tmpl is None:
            failures.append(
                f"{name}: declares local_login_fallback but has no "
                f"compose_extension.template to render the bypass env into"
            )
            continue
        if not tmpl.exists():
            failures.append(f"{name}: compose-extension template missing at {tmpl}")
            continue
        src = tmpl.read_text()

        # 1. A local-login bypass env token must be present.
        if not any(tok in src for tok in LOCAL_LOGIN_ENV_TOKENS):
            failures.append(
                f"{name}: local_login_fallback declared but no "
                f"ALLOW_LOCAL_LOGIN-style env ({'/'.join(LOCAL_LOGIN_ENV_TOKENS)}) "
                f"found in {tmpl.name}"
            )
            continue

        # 2. It must be gated behind the per-service enable_<svc>_local_login
        #    toggle (so it only renders when the operator opts in). Accept the
        #    exact slug-derived var or a generic enable_*_local_login gate.
        gate_re = re.compile(
            r"{%\s*if[^%]*enable_[a-z0-9_]*local_login[^%]*%}", re.IGNORECASE
        )
        if not gate_re.search(src):
            failures.append(
                f"{name}: local-login bypass env present but not behind an "
                f"`{{% if enable_{slug}_local_login ... %}}` gate "
                f"(would render unconditionally)"
            )

    assert not failures, (
        "local_login_fallback declared but not rendered behind its toggle:\n"
        + "\n".join(f"  {f}" for f in failures)
    )
