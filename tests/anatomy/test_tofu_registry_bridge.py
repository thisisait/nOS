"""Anatomy gate — the tofu-authentik registry bridge resolves nested Jinja.

ADR-0001 Phase 1 (2026-06-12). Blank #2 (first tofu-engine blank after the
blueprint-noop fix) died at `tofu apply` with 22× HTTP 400
`external_host: ["Enter a valid URL."]`: the tfvars carried LITERAL
``https://{{ bookstack_domain }}`` strings. The registry
(state/tofu-authentik-services.yml) stores raw Jinja by design, but the task
loaded it with ``lookup('file') | from_yaml`` — and post-2.19 data-tagging
marks such strings untrusted, so Ansible NEVER resolves the nested templates
(the tfvars template's "Ansible resolves the nested Jinja" assumption held
only pre-2.19).

This gate pins the fix:
  1. tasks/tofu-authentik.yml loads the registry via ``lookup('template')``
     (file rendered first, full var scope → resolved values), never
     ``lookup('file')``.
  2. The registry file itself stays renderable as one Jinja template
     (ChainableUndefined → YAML parses, zero ``{{`` survives) — also catches
     the brace-hash class of template-breaking edits (CLAUDE.md gotcha).
"""

from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
REGISTRY = REPO / "state" / "tofu-authentik-services.yml"
TOFU_TASKS = REPO / "tasks" / "tofu-authentik.yml"

sys.path.insert(0, str(REPO / "files" / "anatomy"))


def test_registry_loaded_via_template_lookup():
    src = TOFU_TASKS.read_text()
    assert "lookup('template', playbook_dir + '/state/tofu-authentik-services.yml')" in src, (
        "tofu-authentik must load the registry with lookup('template') — "
        "lookup('file')+from_yaml leaves the nested Jinja unresolved "
        "(untrusted post-2.19) and tofu applies literal '{{ x_domain }}' URLs."
    )
    assert "lookup('file', playbook_dir + '/state/tofu-authentik-services.yml')" not in src, (
        "lookup('file') regression on the registry load — see module docstring."
    )


def test_apply_is_serial():
    """blank #3: authentik_outpost_provider_attachment is read-modify-write
    over the outpost providers LIST; parallel apply (default 10) raced 20
    attachment writes and last-writer-wins kept 11 — 9 forward_auth services
    404'd at the outpost. Apply must stay -parallelism=1."""
    src = TOFU_TASKS.read_text()
    apply_lines = [l for l in src.splitlines() if "tofu apply" in l and "command" in l]
    assert apply_lines, "no tofu apply command found in tasks/tofu-authentik.yml"
    for line in apply_lines:
        assert "-parallelism=1" in line, (
            f"tofu apply must run with -parallelism=1 (outpost m2m race): {line.strip()!r}"
        )


def test_registry_covers_tier2_app_manifests():
    """Tier-2 apps/<name>.yml with an authentik: block must be in the
    registry — under engine=tofu the blueprint render is a no-op, so tofu is
    their ONLY provider-creator (blank #3: documenso/roundcube/twofauth had
    no provider at all). Also: no duplicate slugs (qdrant appears via both a
    Tier-1 plugin and a Tier-2 manifest; the tfvars map would silently keep
    the last)."""
    registry_slugs = [
        s["slug"]
        for s in yaml.safe_load(REGISTRY.read_text())["tofu_authentik_services"]
    ]
    assert len(registry_slugs) == len(set(registry_slugs)), (
        "duplicate slugs in the registry — generator dedupe regressed"
    )
    apps_root = REPO / "apps"
    for app_yml in sorted(apps_root.glob("*.yml")):
        if app_yml.name.startswith("_") or ".draft" in app_yml.name:
            continue
        manifest = yaml.safe_load(app_yml.read_text()) or {}
        ak = manifest.get("authentik") or {}
        slug = ak.get("slug")
        if not slug:
            continue
        assert slug in registry_slugs, (
            f"apps/{app_yml.name} declares authentik.slug={slug!r} but the "
            "registry misses it — re-run tools/tofu-authentik-gen-registry.py "
            "(the generator must harvest app manifests, not just plugins)."
        )


def test_registry_renders_and_parses_as_yaml():
    """Render the registry like lookup('template') will (ChainableUndefined →
    unknown vars collapse to ''), then require valid YAML with zero surviving
    Jinja delimiters in any value."""
    from module_utils.load_plugins import _jinja_env  # noqa: WPS433 (lazy)

    rendered = _jinja_env().from_string(REGISTRY.read_text()).render(
        {"tenant_domain": "dev.local", "global_password_prefix": "test"}
    )
    assert "{{" not in rendered and "{%" not in rendered, (
        "registry render left Jinja delimiters behind — a value the template "
        "engine cannot resolve will reach tofu literally."
    )
    doc = yaml.safe_load(rendered)
    services = doc["tofu_authentik_services"]
    assert services, "registry rendered to an empty service list"
    for svc in services:
        host = svc.get("external_host", "")
        assert host.startswith("https://"), (
            f"{svc.get('slug')}: external_host {host!r} is not a https URL "
            "after render — Authentik will 400 on 'Enter a valid URL'."
        )
