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
