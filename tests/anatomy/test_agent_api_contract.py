"""Anatomy gate — the agent-facing API surface (W5-A2/A3).

Originally titled for the scout/remediator agents, whose reports surfaced the
defects pinned here (GET /api/v1/notifications 404; token-scope 401 on state).
Both agents were retired in the 2026-08-26 roster close — the API contracts
they surfaced outlive them, because every runner agent uses the same surface.
Retired-agent wiring tests left with their subjects (test_agent_roster_close.py
pins the retirement); live-agent wiring is asserted against upgrade-architect.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing/app"
ROUTER = WING / "Core/RouterFactory.php"
NOTIF_PRESENTER = WING / "Presenters/Api/NotificationsPresenter.php"


def test_notifications_read_route_exists():
    """W5-A2: GET /api/v1/notifications must route to a presenter (scout's
    severity-spike signal). Previously 404."""
    router = ROUTER.read_text()
    assert "api/v1/notifications" in router, "notifications route not registered"
    assert "Notifications:default" in router
    assert NOTIF_PRESENTER.is_file(), "Api\\NotificationsPresenter missing"


def test_notifications_presenter_is_read_only_bearer():
    src = NOTIF_PRESENTER.read_text()
    # Bearer-auth (no publicActions opt-out) + GET-only (creation stays on Bone).
    assert "publicActions" not in src, "notifications read must require bearer auth"
    assert "requireMethod('GET')" in src, "notifications endpoint must be GET-only"


def test_apps_runner_deploy_events_carry_attribution():
    """W5-A4: scout flagged app.deployed events as null actor_id +
    actor_action_id + bare-timestamp run_id. The apps_runner post must stamp a
    service actor_id and a run-level UUID actor_action_id so the events are
    attributable (and group as one deploy run)."""
    post = (REPO / "roles/pazny.apps_runner/tasks/post.yml").read_text()
    assert "'actor_id': 'apps_runner'" in post, "app.deployed must carry actor_id"
    assert "'actor_action_id': _apps_action_id" in post, "app.deployed must carry a run-level actor_action_id"
    assert "| to_uuid" in post, "actor_action_id must be a UUID, not a bare timestamp"


def test_upgrades_planned_queue_wired():
    """W5-B2: the planned-upgrade queue must be writable (API + operator) and
    feed the matrix. Pins the queue endpoint + repo methods + route."""
    router = (REPO / "files/anatomy/wing/app/Core/RouterFactory.php").read_text()
    assert "Upgrades:queue" in router, "API queue route missing"
    assert "Upgrades:queueUpgrade" in router, "operator queue route missing"
    api = (REPO / "files/anatomy/wing/app/Presenters/Api/UpgradesPresenter.php").read_text()
    assert "function actionQueue" in api and "getActorId" in api, "queue must derive planned_by from the token"
    repo = (REPO / "files/anatomy/wing/app/Model/UpgradeRepository.php").read_text()
    for m in ("function planUpgrade", "function listPlanned", "function markPlannedApplied"):
        assert m in repo, f"UpgradeRepository missing {m}"


def test_upgrade_engine_consumes_planned_queue():
    """W5-B3: the upgrade-engine must apply queued upgrades ONLY under --tags
    upgrade (never on a normal run): read the planned keys, make them eligible
    (OR with from_regex auto-detect), and mark them applied after a real run."""
    engine = (REPO / "tasks/upgrade-engine.yml").read_text()
    assert "planned-upgrades.php --list" in engine, "engine must read the planned queue"
    assert "_planned_keys" in engine, "engine must use planned keys for eligibility"
    assert "--mark-applied" in engine, "engine must mark planned upgrades applied"
    # Mark-applied must be skipped on dry-run.
    assert "upgrade_dry_run" in engine
    bin_ = (REPO / "files/anatomy/wing/bin/planned-upgrades.php")
    assert bin_.is_file(), "planned-upgrades.php bridge missing"
    src = bin_.read_text()
    assert "--list" in src and "mark-applied" in src


def test_upgrade_matrix_reads_installed_from_state():
    """W5-B1 fix (2026-05-27): the /upgrades 'installed' column was blank
    because matrix() read systems.version (mostly NULL). It must read the
    authoritative ~/.nos/state.yml services.<id>.installed (same source the
    upgrade-engine uses), and differentiate stable (applicable next step via
    from_pattern) from latest (highest target)."""
    repo = (REPO / "files/anatomy/wing/app/Model/UpgradeRepository.php").read_text()
    assert "installedVersionsFromState" in repo, "matrix must read installed from state.yml"
    assert ".nos/state.yml" in repo
    assert "from_pattern" in repo, "stable must be the applicable (from_pattern-matched) step"


def test_upgrade_queue_mismatch_guard():
    """2026-05-27: queueing a recipe whose from_pattern doesn't match the
    installed version is REFUSED (409 / mismatch) unless force=true — that is
    how a downgrade got queued (authentik-2024-to-2025 on a 2025.12.4 install).
    Status transitions must also survive the UNIQUE(service,recipe_id,status)
    constraint on repeat apply/cancel."""
    repo = (REPO / "files/anatomy/wing/app/Model/UpgradeRepository.php").read_text()
    assert "function recipeMismatch" in repo, "mismatch guard helper missing"
    assert "bool $force" in repo, "planUpgrade must accept a force override"
    assert "from-pattern" in repo, "mismatch detail must explain the from_pattern miss"
    # repeat-apply / repeat-cancel must not collide on the UNIQUE constraint.
    assert "->where('status', 'applied')\n\t\t\t->delete()" in repo or "where('status', 'applied')->delete()" in repo
    api = (REPO / "files/anatomy/wing/app/Presenters/Api/UpgradesPresenter.php").read_text()
    assert "'mismatch'" in api and "409" in api, "API queue must 409 on mismatch"


def test_agent_token_requests_capability_scopes():
    """W5-A3 (2026-05-27): Authentik client_credentials grants only REQUESTED
    scopes, so the runner must request the agent's capabilities in the token
    mint — otherwise the JWT scope claim is empty and every scoped Bone
    endpoint (/api/state, migrations, upgrades) 403s. (The scout-profile
    Bone-vs-Wing steer this test also pinned died with the scout, 2026-08-26;
    the runner-side scope mint is agent-agnostic and stays.)"""
    runner = (REPO / "files/anatomy/scripts/pulse-run-agent.sh").read_text()
    assert "AGENT_SCOPES" in runner, "runner must derive the agent scopes"
    assert "scope=${AGENT_SCOPES}" in runner, "runner must request scopes in the token mint"
    assert "/^capabilities:/" in runner, "scopes derived from the profile capabilities list"


# test_upgrade_advisor_agent_wired was deleted with its subject (2026-08-26
# roster close; deterministic since UpgradeRepository::compareVersions,
# cab67496/b1e92005). test_agent_roster_close.py pins the absence; the
# wiring checklist survives on the live architect below.


def test_agent_clients_blueprint_is_force_applied():
    """2026-05-27: the 'Reapply authentik blueprints' handler must apply
    30-agent-clients. It was rendered but excluded from the apply loop, so a
    newly-added agent OAuth client (e.g. upgrade-advisor) was never provisioned
    outside a full blank → client_credentials mint returned invalid_client."""
    for f in ("main.yml", "roles/pazny.authentik/handlers/main.yml"):
        src = (REPO / f).read_text()
        # Find the reapply loop and assert 30-agent-clients is in it.
        assert "30-agent-clients" in src, f"{f}: reapply handler must apply 30-agent-clients"


def test_pulse_catalog_points_at_agent_wing_tokens():
    """2026-05-27: discover-pulse-catalog.py does LITERAL substring substitution
    on a FIXED token map (no Jinja). A new agent's {{ <agent>_wing_api_token }}
    must be in that map, or its WING_API_TOKEN stays the literal placeholder and
    every API call 401s (first hit by upgrade-advisor, retired 2026-08-26 —
    the property is agent-agnostic, so it is asserted on the live architect).

    CHANGED 2026-08-11: the map now yields a REFERENCE (`secret:<name>`) rather
    than the value. The old shape is what put nineteen credentials in the clear
    into `pulse_jobs.env_json`, and the `NOS_*` env export was removed with it —
    an unused secret in a process environment is still a secret in a process
    environment. The token itself is unchanged and still provisions its
    `api_tokens` row a few tasks further down.
    """
    cat = (REPO / "files/anatomy/scripts/discover-pulse-catalog.py").read_text()
    assert "{{ upgrade_architect_wing_api_token }}" in cat, "catalog substitution map missing upgrade_architect token"
    assert '"secret:upgrade_architect_wing_api_token"' in cat, (
        "the map no longer yields a reference for this token — check whether it "
        "went back to substituting the value"
    )
    assert "NOS_UPGRADE_ARCHITECT_WING_API_TOKEN" not in cat, (
        "the catalog reads the token's value from the environment again"
    )
    # The name must still be resolvable, or the job refuses at exec time.
    store = (REPO / "templates/secrets.yml.j2").read_text()
    assert "upgrade_architect_wing_api_token:" in store, (
        "the token is referenced but the secrets template never writes that "
        "name, so the Pulse daemon cannot resolve it"
    )


def test_upgrade_architect_agent_wired():
    """W5-B5: the upgrade-architect agent (drafts recipes for coverage gaps in
    its report + queues coexistence for breaking) must be fully wired with the
    complete new-agent provisioning checklist (contract, profile, wrapper,
    Authentik client, wing token: credentials + catalog substitution + post
    provision + env). Propose-only — never writes files or provisions."""
    base = REPO / "files/anatomy/agents"
    for f in ("upgrade-architect/agent.yml", "upgrade-architect/system.md", "upgrade-architect/rubric.md", "upgrade-architect/agent.yml"):
        assert (base / f).is_file(), f"missing: {f}"
    assert (REPO / "tools/run-upgrade-architect.sh").is_file()
    assert 'client_id: "nos-upgrade-architect"' in (REPO / "default.config.yml").read_text()
    assert "upgrade_architect_wing_api_token" in (REPO / "default.credentials.yml").read_text()
    cat = (REPO / "files/anatomy/scripts/discover-pulse-catalog.py").read_text()
    assert "{{ upgrade_architect_wing_api_token }}" in cat and '"secret:upgrade_architect_wing_api_token"' in cat
    post = (REPO / "roles/pazny.wing/tasks/post.yml").read_text()
    # The env half went with the secret-reference change (2026-08-11): the
    # catalog resolves the name at exec time, so the value no longer travels to
    # its subprocess. Provisioning the api_tokens row is the half that matters
    # and is asserted directly.
    assert "--name=upgrade-architect" in post
    assert "--token={{ upgrade_architect_wing_api_token }}" in post
    prof = (base / "upgrade-architect/agent.yml").read_text()
    assert "/coexistence/" in prof and "queue" in prof, "architect must queue coexistence"
    assert "never write" in prof.lower() or "propose-only" in prof.lower() or "never write/commit" in prof.lower()


def test_coexistence_queue_consumed_under_tag():
    """W5-B5c (2026-05-27): the coexistence_planned queue (architect/operator
    queues a parallel-track provision for a breaking upgrade) must be consumed
    ONLY under --tags coexistence (never on a normal run), with the new track
    resolved against the manifest (real stack + base port from port_var) so it
    clears the live legacy install."""
    # Queue surface: table column, repo, API, bridge.
    schema = (REPO / "files/anatomy/wing/db/schema-extensions.sql").read_text()
    assert "coexistence_planned" in schema and "target_version" in schema
    repo = (REPO / "files/anatomy/wing/app/Model/CoexistenceRepository.php").read_text()
    for m in ("function planCoexistence", "function listPlanned", "function markPlannedApplied"):
        assert m in repo, f"CoexistenceRepository missing {m}"
    api = (REPO / "files/anatomy/wing/app/Presenters/Api/CoexistencePresenter.php").read_text()
    assert "function actionQueue" in api and "getActorId" in api, "queue must derive planned_by from the token"
    bridge = (REPO / "files/anatomy/wing/bin/planned-coexistence.php")
    assert bridge.is_file(), "planned-coexistence.php bridge missing"
    assert "--list" in bridge.read_text() and "mark-applied" in bridge.read_text()
    # init-db must ALTER target_version into existing coexistence_planned tables.
    initdb = (REPO / "files/anatomy/wing/bin/init-db.php").read_text()
    assert "'coexistence_planned'" in initdb and "target_version" in initdb, "init-db must add target_version to existing tables"
    # Consumer: tag-gated, manifest-resolved, dry-run-safe mark.
    consumer = (REPO / "tasks/coexistence-apply.yml").read_text()
    assert "planned-coexistence.php --list" in consumer, "consumer must read the queue"
    assert "_coexist_manifest" in consumer and "manifest.yml" in consumer, "consumer must resolve stack/port from the manifest"
    assert "coexist_base_port" in consumer and "port_var" in consumer, "base_port must come from the manifest port_var"
    assert "coexist_dry_run" in consumer and "--mark-applied" in consumer
    # Wired into main.yml behind 'never' so a normal run never provisions.
    main = (REPO / "main.yml").read_text()
    assert "tasks/coexistence-apply.yml" in main, "consumer not imported in main.yml"
    # Real-apply (no -e) regressions found 2026-05-28, masked by dry-run -e:
    # (1) coexist_dry_run must NOT be a self-referential include var (recursed
    #     when no -e broke the loop); (2) the nginx reload must be gated on
    #     install_nginx (brew reload nginx fails on a Traefik-primary install).
    assert "NOT forwarded here" in consumer, "coexist_dry_run self-reference (recursion) must stay removed"
    prov = (REPO / "tasks/coexistence-provision.yml").read_text()
    assert "install_nginx" in prov, "nginx reload must be gated on install_nginx (Traefik-primary has no nginx)"


def test_agent_exit_verdict_sentinel_propagated():
    """2026-05-28: claude --print exits 0 on success regardless of the agent's
    conclusion, so the run-tools showed GREEN even when a breaking upgrade was
    queued. Agents end their report with a `NOS_AGENT_EXIT: N` sentinel; the
    runner lifts it into the process exit (escalate-only, never masking a real
    claude failure). Verified live: advisor → exit 1 → wrapper REVIEW."""
    runner = (REPO / "files/anatomy/scripts/pulse-run-agent.sh").read_text()
    assert "NOS_AGENT_EXIT" in runner, "runner must parse the verdict sentinel"
    assert "AGENT_VERDICT" in runner and "-gt 0" in runner, "escalate-only (don't mask a real failure)"
    # Both review-capable agents, both runtime forms, must instruct the sentinel.
    # (upgrade-advisor was in this loop until its 2026-08-26 retirement —
    # "Verified live: advisor -> exit 1" above is that agent's one live run.)
    for p in ("upgrade-architect/agent.yml", "upgrade-architect/system.md"):
        assert "NOS_AGENT_EXIT" in (REPO / "files/anatomy/agents" / p).read_text(), \
            f"{p}: must instruct the exit-verdict sentinel"
