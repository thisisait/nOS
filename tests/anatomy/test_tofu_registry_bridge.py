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

import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
REGISTRY = REPO / "state" / "tofu-authentik-services.yml"
TOFU_TASKS = REPO / "tasks" / "tofu-authentik.yml"
TFVARS_TEMPLATE = REPO / "templates" / "tofu" / "nos.auto.tfvars.json.j2"
ADOPT = REPO / "tools" / "tofu-authentik-adopt.sh"

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


def test_registry_entries_carry_enabled():
    """Disabled-service filtering: every registry entry must carry the raw
    Jinja enable expression (e.g. '{{ install_erpnext | default(false) }}').
    Without it the tfvars template's `enabled | default(false) | bool` filter
    silently drops the service — an entry MISSING the field is a generator
    regression, not an intentional disable."""
    services = yaml.safe_load(REGISTRY.read_text())["tofu_authentik_services"]
    missing = [s.get("slug") for s in services if "enabled" not in s]
    assert not missing, (
        f"registry entries missing 'enabled': {missing} — re-run "
        "tools/tofu-authentik-gen-registry.py (it must carry each client's "
        "enable expression verbatim)."
    )


def test_disabled_service_filtered_from_tfvars():
    """End-to-end filter semantics: render the registry like
    lookup('template') will (install_erpnext UNDEFINED → ChainableUndefined →
    `default(false)` → the string 'False'), then render the tfvars template
    over the parsed services and assert the disabled service never reaches
    var.authentik_services while an enabled one does. The loader _jinja_env
    registers both `bool` and `to_nice_json`, so the tfvars template renders
    1:1 with the playbook's task-time templating."""
    from module_utils.load_plugins import _jinja_env  # noqa: WPS433 (lazy)

    env = _jinja_env()
    rendered = env.from_string(REGISTRY.read_text()).render(
        {
            "tenant_domain": "dev.local",
            "global_password_prefix": "test",
            "install_gitea": True,
            # install_erpnext deliberately UNDEFINED → renders "False"
        }
    )
    services = yaml.safe_load(rendered)["tofu_authentik_services"]
    by_slug = {s["slug"]: s for s in services}
    # The rendered file quotes the value, so it arrives as the STRING "False"
    # (not a YAML bool) — exactly what the tfvars `| bool` filter must coerce.
    assert by_slug["erpnext"]["enabled"] == "False", (
        f"expected erpnext enabled to render to the string 'False', got "
        f"{by_slug['erpnext']['enabled']!r}"
    )
    tfvars = json.loads(
        env.from_string(TFVARS_TEMPLATE.read_text()).render(
            {
                "tofu_authentik_services": services,
                "authentik_bootstrap_token": "test-token",
                "authentik_port": 9000,
            }
        )
    )
    svcmap = tfvars["authentik_services"]
    assert "gitea" in svcmap, (
        "install_gitea=True yet gitea missing from authentik_services — the "
        "tfvars enabled-filter is over-eager (string 'True' must pass | bool)."
    )
    assert "erpnext" not in svcmap, (
        "install_erpnext undefined (→ 'False') yet erpnext landed in "
        "authentik_services — the tfvars template must skip services whose "
        "rendered enabled value is falsy."
    )


def test_adopt_emits_attachment_imports():
    """Adopt-path attachment import id (P3, existing-tenant only).

    A proxy provider is useless until it is bound to the embedded outpost —
    forward_auth 404s otherwise. The adopt script must therefore import the
    `authentik_outpost_provider_attachment` resources too, NOT just the
    providers; if it omits them the adopt plan reads `N to add` for the
    attachments and the operator hits a cryptic import failure.

    Confirmed import id format (from the live terraform.tfstate: every
    attachment serializes id = "<outpost_uuid>:<provider_pk>"). The provider
    does not round-trip the `provider` attr into state, so the id is the only
    carrier and must be exact: the script composes it as `${OUTPOST_ID}:<pk>`.
    This gate pins both the enumeration AND the id shape.
    """
    src = ADOPT.read_text()

    # the resource type is enumerated at all
    assert "authentik_outpost_provider_attachment" in src, (
        "tofu-authentik-adopt.sh must import "
        "authentik_outpost_provider_attachment resources — a proxy provider "
        "without its embedded-outpost binding 404s on forward_auth."
    )

    # the embedded outpost id is resolved via the instances API
    assert "/outposts/instances/" in src, (
        "adopt script must resolve the embedded outpost id "
        "(GET /api/v3/outposts/instances/) to compose the attachment import id."
    )
    assert "authentik Embedded Outpost" in src, (
        "adopt script must select the embedded outpost by name."
    )

    # the import id is composed as "<outpost_uuid>:<provider_pk>"
    assert "{op}:{p['pk']}" in src, (
        "attachment import id must be '<outpost_uuid>:<provider_pk>' — the "
        "confirmed terraform.tfstate format. Any other shape imports with a "
        "cryptic error and the operator has to debug the API by hand."
    )

    # each proxy provider yields BOTH a provider AND an attachment import block
    assert "adopt_attach_" in src, (
        "each proxy provider must emit a paired attachment import block "
        "(adopt_attach_<name>) alongside the provider import."
    )


def _config_install_vars() -> set[str]:
    """Every `install_*` key DEFINED in default.config.yml — the only vars that
    resolve BEFORE tasks/tofu-authentik.yml runs (role defaults load later, in
    stack-up). The registry's enabled expressions may reference only these."""
    txt = (REPO / "default.config.yml").read_text()
    return set(re.findall(r"(?m)^(install_[a-z0-9_]+):", txt))


def test_registry_enabled_refs_are_defined_install_vars():
    """STATIC validation of every registry `enabled` expression.

    A typo in an install_* var name (e.g. `install_n8n_typo`) is INVISIBLE at
    render time: ChainableUndefined + `| default(false)` collapses it to the
    string 'False' — indistinguishable from a service legitimately toggled off,
    so the tfvars `| bool` filter silently drops it and the service never gets
    an Authentik provider. Same trap when the enabled field references a var
    defined only in a role default (loaded during stack-up, AFTER
    tasks/tofu-authentik.yml renders the tfvars) — it is undefined at render
    time and renders to 'False'.

    The only deterministic catch is static: every install_* identifier in an
    enabled expression MUST be a key in default.config.yml (the source loaded
    before core-up/tofu-authentik). This pins the contract and would have
    surfaced the hermes_domain-class "referenced-but-loaded-too-late" bug.
    """
    defined = _config_install_vars()
    services = yaml.safe_load(REGISTRY.read_text())["tofu_authentik_services"]
    offenders: list[str] = []
    for svc in services:
        enabled = str(svc.get("enabled", ""))
        for ident in re.findall(r"install_[a-z0-9_]+", enabled):
            if ident not in defined:
                offenders.append(f"{svc.get('slug')}: enabled refs {ident!r}")
    assert not offenders, (
        "registry enabled expression references an install_* var NOT defined in "
        "default.config.yml — it renders to the string 'False' (ChainableUndefined "
        "+ default) and SILENTLY disables the service. Fix the typo, or add a real "
        "default to default.config.yml (a role default loads too late). Offenders:\n  "
        + "\n  ".join(offenders)
    )


def test_registry_enabled_render_coerces_to_bool():
    """END-TO-END render validation: render the registry with EVERY install_*
    var from default.config.yml force-set True, then assert every entry's
    rendered enabled value coerces to a real boolean (the tfvars `| bool` input
    contract). A bare-literal `enabled: true` stays 'true'; a Jinja expression
    resolves to 'True'/'False' — both are bool-coercible. An empty string (an
    unresolved expression that produced nothing) is NOT, and fails here."""
    from module_utils.load_plugins import _jinja_env  # noqa: WPS433 (lazy)

    ctx = {
        "tenant_domain": "dev.local",
        "global_password_prefix": "test",
    }
    ctx.update({v: True for v in _config_install_vars()})
    rendered = _jinja_env().from_string(REGISTRY.read_text()).render(ctx)
    services = yaml.safe_load(rendered)["tofu_authentik_services"]
    truthy = {"true", "false", "yes", "no", "1", "0", "on", "off"}
    bad: list[str] = []
    for svc in services:
        val = str(svc.get("enabled", "")).strip().lower()
        if val not in truthy:
            bad.append(f"{svc.get('slug')}: enabled rendered to {svc.get('enabled')!r}")
    assert not bad, (
        "a registry enabled value did not render to a bool-coercible token — the "
        "tfvars `| bool` filter will mis-handle it. Offenders:\n  " + "\n  ".join(bad)
    )


def test_oauth2_module_declares_grant_types():
    """Authentik 2026.5.x made OAuth2Provider.grant_types an explicit
    ArrayField — a provider created WITHOUT it has an empty list and every
    authorization_code request dies with invalid_request "The request is
    otherwise malformed" (live: grafana + gitlab SSO broke after the tofu
    cutover; the blueprint always set the field). Mirror of
    test_oauth2_grant_types.py for the HCL side: minimal set, no ROPC."""
    module_tf = (REPO / "modules" / "nos-authentik-app" / "main.tf").read_text()
    assert 'grant_types         = ["authorization_code", "refresh_token"]' in module_tf, (
        "authentik_provider_oauth2 must declare grant_types "
        '["authorization_code", "refresh_token"] — without it Authentik '
        "2026.5.x+ rejects every native_oidc login."
    )
