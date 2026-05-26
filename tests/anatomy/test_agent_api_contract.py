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
