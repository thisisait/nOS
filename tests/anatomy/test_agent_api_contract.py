"""Anatomy gate — API surface the scout/remediator agents depend on (W5-A2/A3).

The scout's drift report surfaced two endpoints its rubric calls that weren't
usable: GET /api/v1/notifications (404 — no route) and GET /api/v1/state (401 —
token scope). Both made signals permanently un-evaluable. Pin the routes /
presenter so the agent contract can't silently drift from the API.
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
