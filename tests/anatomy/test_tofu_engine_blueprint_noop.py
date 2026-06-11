"""Anatomy gate — 10-oidc-apps must be a client no-op under authentik_engine=tofu.

ADR-0001 Phase 1 (2026-06-11). The first tofu-engine blank
(`-e blank=true`, `authentik_engine: tofu`) died at `tofu apply` with 36×
HTTP 400 "provider with this name already exists": Authentik AUTO-APPLIES
every blueprint in the bind-mounted /blueprints/custom (container start +
inotify file change), so gating the `ak apply_blueprint` loops in main.yml
was not enough — the rendered 10-oidc-apps.yaml itself created all providers
before OpenTofu's create-only plan applied.

This gate pins the structural fix:
  1. Under authentik_engine=tofu the template renders ZERO client entries
     (no oauth2provider / proxyprovider / application models).
  2. The embedded-outpost entry survives but OMITS the `providers:` key —
     a blueprint apply must never unbind tofu-attached providers. Its
     `config:` (authentik_host) stays blueprint-owned.
  3. Default engine ('blueprint', or unset) renders unchanged — full client
     entries + outpost provider bindings.
  4. Both `ak apply_blueprint` loops (main.yml play-level handler + the
     role-local handler) drop 10-oidc-apps when engine=tofu.

Render strategy mirrors test_autologin_blueprint_binding_present.py: the
production loader env (`module_utils.load_plugins._jinja_env`) so the render
is byte-identical to the live blueprint render path.
"""

from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
BLUEPRINTS = REPO / "files" / "anatomy" / "plugins" / "authentik-base" / "blueprints"
OIDC_J2 = BLUEPRINTS / "10-oidc-apps.yaml.j2"
ROLE_HANDLER = REPO / "roles" / "pazny.authentik" / "handlers" / "main.yml"
MAIN_YML = REPO / "main.yml"

CLIENT_MODELS = {
    "authentik_providers_oauth2.oauth2provider",
    "authentik_providers_proxy.proxyprovider",
    "authentik_core.application",
}
OUTPOST_MODEL = "authentik_outposts.outpost"

ENGINE_GATE = "if (authentik_engine | default('blueprint')) != 'tofu'"

sys.path.insert(0, str(REPO / "files" / "anatomy"))


class _FindLoader(yaml.SafeLoader):
    """SafeLoader tolerant of Authentik's ``!Find [model, [k, v]]`` tags."""


_FindLoader.add_constructor(
    "!Find",
    lambda loader, node: {"__Find__": loader.construct_sequence(node, deep=True)},
)


def _clients() -> list[dict]:
    return [
        {
            "mode": "native_oidc",
            "client_id": "nos-grafana",
            "client_secret": "s",
            "slug": "grafana",
            "name": "Grafana",
            "tier": 1,
            "enabled": True,
            "redirect_uris": ["https://grafana.dev.local/login/generic_oauth"],
            "launch_url": "https://grafana.dev.local",
        },
        {
            "mode": "forward_auth",
            "slug": "kuma",
            "name": "Uptime Kuma",
            "tier": 3,
            "enabled": True,
            "external_host": "https://kuma.dev.local",
        },
    ]


def _render(extra_ctx: dict) -> dict:
    from module_utils.load_plugins import _jinja_env  # noqa: WPS433 (lazy)

    tmpl = _jinja_env().from_string(OIDC_J2.read_text())
    ctx = {
        "inputs": {"clients": _clients()},
        "authentik_oidc_apps": [],
        "tenant_domain": "dev.local",
    }
    ctx.update(extra_ctx)
    return yaml.load(tmpl.render(ctx), Loader=_FindLoader)


def _models(doc: dict) -> list[str]:
    return [e.get("model") for e in (doc.get("entries") or [])]


# ── engine=tofu: client layer is OpenTofu's ────────────────────────────────


def test_tofu_engine_renders_zero_client_entries():
    doc = _render({"authentik_engine": "tofu"})
    leaked = [m for m in _models(doc) if m in CLIENT_MODELS]
    assert not leaked, (
        f"engine=tofu must render NO provider/application entries, got {leaked} "
        "— Authentik auto-applies the mounted blueprint and the next tofu-engine "
        "blank dies on 'provider with this name already exists' again."
    )


def test_tofu_engine_outpost_keeps_config_but_omits_providers():
    doc = _render({"authentik_engine": "tofu"})
    outposts = [e for e in doc["entries"] if e.get("model") == OUTPOST_MODEL]
    assert len(outposts) == 1, "embedded-outpost entry must survive engine=tofu"
    attrs = outposts[0]["attrs"]
    assert "providers" not in attrs, (
        "outpost entry must OMIT `providers:` under engine=tofu — a blueprint "
        "apply would unbind the providers tofu attached "
        "(authentik_outpost_provider_attachment)."
    )
    assert "config" in attrs and attrs["config"].get("authentik_host"), (
        "outpost `config:` (authentik_host) stays blueprint-owned under tofu"
    )


# ── engine=blueprint (and unset): unchanged behavior ───────────────────────


def test_blueprint_engine_renders_clients_and_outpost_bindings():
    for ctx in ({}, {"authentik_engine": "blueprint"}):
        doc = _render(ctx)
        models = _models(doc)
        assert "authentik_providers_oauth2.oauth2provider" in models
        assert "authentik_providers_proxy.proxyprovider" in models
        outpost = next(e for e in doc["entries"] if e.get("model") == OUTPOST_MODEL)
        assert outpost["attrs"].get("providers"), (
            f"engine={ctx.get('authentik_engine', '<unset>')} must keep outpost "
            "provider bindings"
        )


# ── both ak apply_blueprint loops carry the engine gate ────────────────────


def test_apply_blueprint_loops_gate_oidc_apps_on_engine():
    for path in (MAIN_YML, ROLE_HANDLER):
        src = path.read_text()
        gated = f"{{{{ ' 10-oidc-apps' {ENGINE_GATE} else '' }}}}"
        assert gated in src, (
            f"{path.relative_to(REPO)}: the `ak apply_blueprint` loop must gate "
            "10-oidc-apps on authentik_engine != 'tofu' (ADR-0001 Phase 1)."
        )
        loop_lines = [l for l in src.splitlines() if "for bp in" in l]
        assert loop_lines, f"{path.relative_to(REPO)}: no `for bp in` apply loop?"
        for line in loop_lines:
            assert " 10-oidc-apps" not in line.replace(gated, ""), (
                f"{path.relative_to(REPO)}: UNgated bare `10-oidc-apps` in an "
                f"apply loop: {line.strip()!r}"
            )
