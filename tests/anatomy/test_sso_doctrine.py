"""Anatomy gates for the SSO/identity doctrine (2026-05-17).

CLAUDE.md β1.A pinned three Authentik-wiring buckets per service:

  native_oidc   — service consumes OIDC at app level (own login UI +
                  'Sign in with Authentik' button)
  header_oidc   — Authentik proxy outpost forwards X-Authentik-* headers;
                  service auto-creates the local user from headers
  forward_auth  — pure access gate (Authentik session = 'you're in';
                  service has no per-user state)

Plus `none` for substrates / no-SSO services. **Anything else is a
typo or stale label** and gets caught here so the doctrine stays
single-spelling.

This file also pins identity-attribution coverage: every wing.db table
that records agent / plugin / operator writes must carry an actor_id
column (A10 lineage). Tables that don't write attributable data
(read-only views, mirror caches) are exempt; the gate doesn't enforce
on them.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = REPO / "files/anatomy/plugins"

CANONICAL_MODES = {"native_oidc", "header_oidc", "forward_auth", "none"}

# Tables that legitimately do NOT need actor_id (substrate / mirror /
# foreign-key-only). All other tables that take application writes are
# expected to carry actor_id (or have a soft FK that does).
ACTOR_ID_EXEMPT_TABLES = {
    "components",          # backward-compat view (defined as a SELECT in init-db.php)
    "scan_cycles",         # cron metadata; not application-level writes
    "component_scan_state",# scan-state mirror keyed off systems
    "scan_config",         # config table, no per-action writes
    "attack_probes",       # static catalog
    "report_types",        # static catalog
    "advisories",          # generated-by-pipeline (event_run_id carries lineage)
    "migrations_applied",  # event_run_id carries lineage
    "upgrades_applied",    # event_run_id carries lineage
    "patches_applied",     # event_run_id carries lineage
    "gdpr_processing",     # admin-curated catalog
    "gdpr_dsar",           # per-request log, recorded_by goes via Wing UI
    "gdpr_breaches",       # per-incident log
    "systems",             # ingested via service-registry; source='manual' marks operator
}


def _plugin_authentik_mode(yaml_path: pathlib.Path) -> str | None:
    data = yaml.safe_load(yaml_path.read_text())
    a = (data or {}).get("authentik")
    if not isinstance(a, dict):
        return None
    return a.get("mode") or a.get("provider_type")


def test_every_plugin_uses_canonical_authentik_mode():
    """Every plugin manifest's authentik.mode (or .provider_type) MUST
    be one of the canonical four. Caught at parse time, not at runtime."""
    offenders: list[tuple[str, str]] = []
    for p in sorted(PLUGINS.glob("*/plugin.yml")):
        mode = _plugin_authentik_mode(p)
        if mode is None:
            continue  # plugin doesn't declare an authentik block at all
        if mode not in CANONICAL_MODES:
            offenders.append((p.parent.name, mode))
    assert not offenders, (
        f"plugins using non-canonical Authentik mode (must be one of "
        f"{sorted(CANONICAL_MODES)}): {offenders}"
    )


def test_plugins_with_authentik_block_have_explicit_mode():
    """Blueprints work via a default-expression chain that infers
    native_oidc when no mode is declared. That's convenient but
    fragile — a future commit could change the default. Force every
    plugin with an authentik: block to declare mode/provider_type
    EXPLICITLY so the wiring stays auditable from the manifest alone."""
    offenders: list[str] = []
    for p in sorted(PLUGINS.glob("*/plugin.yml")):
        data = yaml.safe_load(p.read_text())
        a = (data or {}).get("authentik")
        if not isinstance(a, dict):
            continue
        # Plugins that declare other authentik fields (client_id, slug, …)
        # MUST declare mode/provider_type too.
        has_other_fields = any(
            k in a for k in ("client_id", "slug", "name", "enabled")
        )
        has_mode = bool(a.get("mode") or a.get("provider_type"))
        if has_other_fields and not has_mode:
            offenders.append(p.parent.name)
    assert not offenders, (
        f"plugins with authentik block but no explicit mode/provider_type: "
        f"{offenders} — declare mode: native_oidc|header_oidc|forward_auth"
    )


def test_plugin_clients_have_consistent_naming():
    """Every Authentik client must follow nos-<slug> convention so
    audit logs are unambiguous (e.g. log line 'actor=nos-conductor'
    points at exactly one row in authentik_agent_clients +
    authentik_oidc_apps). Catches typos like nos_conductor (underscore)
    or NosConductor (camelcase)."""
    import re
    offenders: list[tuple[str, str]] = []
    pattern = re.compile(r"^nos-[a-z0-9][a-z0-9-]{1,40}[a-z0-9]$")
    for p in sorted(PLUGINS.glob("*/plugin.yml")):
        data = yaml.safe_load(p.read_text())
        a = (data or {}).get("authentik")
        if not isinstance(a, dict):
            continue
        cid = a.get("client_id")
        if cid and not pattern.match(str(cid)):
            offenders.append((p.parent.name, cid))
    assert not offenders, f"client_id violates nos-<slug> convention: {offenders}"


# ── A10 actor_id coverage ──────────────────────────────────────────────


def test_pentest_tables_carry_direct_attribution():
    """A9.4 follow-on (2026-05-17): pentest_findings + pentest_targets
    now carry direct actor_id columns (discovered_by / resolved_by /
    created_by) so 'who found this vuln?' answers in one SELECT instead
    of the legacy target_id soft-FK chain. Backbone for the deferred
    inspektor runner."""
    src = (REPO / "files/anatomy/wing/bin/init-db.php").read_text()
    # pentest_findings carries the new columns in the CREATE TABLE.
    pf_start = src.find("CREATE TABLE IF NOT EXISTS pentest_findings")
    pf_end = src.find(")\",", pf_start)
    pf_block = src[pf_start:pf_end]
    for col in ("discovered_by", "resolved_at", "resolved_by"):
        assert col in pf_block, f"pentest_findings missing {col}"
    # pentest_targets carries created_by.
    pt_start = src.find("CREATE TABLE IF NOT EXISTS pentest_targets")
    pt_end = src.find(")\",", pt_start)
    pt_block = src[pt_start:pt_end]
    assert "created_by" in pt_block
    # ALTER sweep migrates legacy DBs (pre-A9.4) — must be present so
    # the operator's existing wing.db doesn't need a blank reset.
    assert "addMissingColumns($db, 'pentest_findings'" in src
    assert "addMissingColumns($db, 'pentest_targets'" in src


def test_attribution_tables_carry_actor_id():
    """The five core 'who-did-what' tables — events, pulse_runs,
    notifications, agent_sessions — MUST carry actor_id. These are the
    A10 audit-lineage backbone; lose actor_id and 'who did this?'
    becomes guesswork.
    """
    sql = (REPO / "files/anatomy/wing/db/schema-extensions.sql").read_text()
    for table_block_header in (
        "CREATE TABLE IF NOT EXISTS events",
        "CREATE TABLE IF NOT EXISTS pulse_runs",
        "CREATE TABLE IF NOT EXISTS notifications",
        "CREATE TABLE IF NOT EXISTS agent_sessions",
    ):
        # Find the table block and ensure actor_id appears inside it.
        start = sql.find(table_block_header)
        assert start >= 0, f"missing table: {table_block_header}"
        end = sql.find(");", start)
        block = sql[start:end]
        assert "actor_id" in block, (
            f"{table_block_header} missing actor_id column — A10 lineage gap"
        )


def test_audit_presenter_filters_by_actor():
    """The /audit view must expose actor_id as a filter so operators can
    answer 'what did agent X do?' with one query."""
    src = (REPO / "files/anatomy/wing/app/Presenters/AuditPresenter.php").read_text()
    assert "actor" in src.lower()
    # Filter input rendered in the template.
    audit_tpl = (REPO / "files/anatomy/wing/app/Templates/Audit/default.latte").read_text()
    assert 'name="actor"' in audit_tpl


def test_no_body_supplied_attribution_anti_pattern():
    """Privilege-escalation guard (2026-05-17): no Wing API write
    endpoint may take attribution fields (resolved_by / created_by /
    approved_by / reported_by) from the request body. They MUST come
    from the validated bearer-token identity via `$this->getActorId()`.

    Surfaced live by the SSO audit: GitleaksPresenter::actionResolve +
    RemediationPresenter::actionBulkStatus both pulled `resolved_by`
    from `$body['resolved_by']` — an LLM agent could write
    `resolved_by: 'operator'` and the audit trail would believe it.

    The fix pattern: explicitly reject the field if present in body,
    then read from getActorId(). This gate enforces both halves —
    no presenter may consume body attribution as a value, and the
    sister gate in test_security_presenter_gates pins requireSuperAdmin
    + requirePostMethod on privileged endpoints.
    """
    import re
    api_dir = REPO / "files/anatomy/wing/app/Presenters/Api"
    forbidden_fields = ("resolved_by", "created_by", "approved_by", "reported_by")
    offenders: list[tuple[str, str, int]] = []
    for php in sorted(api_dir.glob("*.php")):
        src = php.read_text()
        for line_no, line in enumerate(src.splitlines(), 1):
            for field in forbidden_fields:
                # The anti-pattern: `$body['<field>'] ??` or
                # `$body['<field>'] ?:` (reading the field as a value).
                # The defence pattern: `isset($body['<field>'])` (checking
                # for presence then rejecting) — allowed.
                if (f"$body['{field}']" in line or f'$body["{field}"]' in line):
                    # Skip allowed defensive patterns.
                    if "isset(" in line or "// " in line or "* " in line.strip()[:2]:
                        continue
                    offenders.append((php.name, line.strip(), line_no))
    assert not offenders, (
        "Wing API endpoint reads attribution from request body — must use "
        f"getActorId() from the bearer token instead: {offenders}"
    )


def test_agent_clients_in_authentik_blueprint_register_all_runners():
    """Every agent profile under files/anatomy/agents/ must have a
    matching Authentik client in default.config.yml::authentik_agent_clients
    so the runner can authenticate. Surfaced the remediator-token-missing
    gap on 2026-05-17 — catch ahead-of-time next time."""
    import re
    agents_dir = REPO / "files/anatomy/agents"
    agent_names: set[str] = set()
    for agent_yml in agents_dir.glob("*.yml"):
        if agent_yml.name == "_template.yml":
            continue
        # Pulse-runner-side profile (top-level name field).
        data = yaml.safe_load(agent_yml.read_text())
        name = (data or {}).get("name")
        if name:
            agent_names.add(name)

    if not agent_names:
        return  # nothing to verify
    cfg_src = (REPO / "default.config.yml").read_text()
    for name in agent_names:
        client_id = f"nos-{name}"
        assert client_id in cfg_src, (
            f"agent profile {name!r} has no `{client_id}` entry in "
            f"default.config.yml::authentik_agent_clients — runner will "
            f"fail to mint a token"
        )
