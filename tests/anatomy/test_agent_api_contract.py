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
