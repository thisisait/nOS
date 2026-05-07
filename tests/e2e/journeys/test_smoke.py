"""Minimal smoke journey — proves the telemetry pipe is wired.

This test:
  1. Opens a journey called 'e2e_smoke'.
  2. Steps through a single Wing /api/v1/events GET (Bearer auth).
  3. Asserts HTTP 200 + valid JSON.
  4. Verifies (via a second step) that the journey's own
     e2e_journey_start row landed in wing.db within the last second.

If this passes, the entire e2e telemetry pipe (pytest fixture → HMAC
POST → wing.db ingest → Wing query) is healthy. Other journeys can
build on this foundation.

Skipped when WING_API_URL is unreachable (smoke test of a smoke test
shouldn't hard-fail — operator might be running pytest on a host
without Wing live).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

import pytest


WING_URL = os.environ.get("WING_API_URL", "http://127.0.0.1:9000").rstrip("/")
WING_TOKEN = os.environ.get("WING_API_TOKEN", "")


def _wing_get(path: str) -> tuple[int, str]:
    req = urllib.request.Request(
        WING_URL + path,
        headers={"Authorization": f"Bearer {WING_TOKEN}"} if WING_TOKEN else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e)


@pytest.fixture(autouse=True)
def _require_wing():
    """Skip the journey suite when Wing isn't live on the configured URL."""
    status, _ = _wing_get("/api/v1/events?limit=1")
    if status == 0:
        pytest.skip(f"Wing not reachable at {WING_URL} — e2e suite is offline")
    if status == 401 and not WING_TOKEN:
        pytest.skip(
            f"WING_API_TOKEN not set; Wing rejected probe with 401 at {WING_URL}"
        )


def test_smoke_pipe_writes_and_reads(journey):
    """Open a journey, write one step, verify it round-trips wing.db."""
    with journey("e2e_smoke") as j:
        with j.step("ping_wing_events_api") as s:
            status, body = _wing_get("/api/v1/events?limit=1")
            assert status == 200, f"Wing /events returned {status}: {body[:200]}"
            data = json.loads(body)
            assert "items" in data, f"missing 'items' key in {data!r}"
            s.note = f"events.total={data.get('total','?')}"

        # Give the start-event time to settle (HMAC POST is fire-and-forget).
        time.sleep(0.4)

        with j.step("verify_journey_start_event_landed") as s:
            url = (
                f"/api/v1/events?actor_action_id={j.actor_action_id}"
                f"&type=e2e_journey_start&limit=1"
            )
            status, body = _wing_get(url)
            assert status == 200, body[:200]
            data = json.loads(body)
            assert data["total"] >= 1, (
                f"e2e_journey_start row not found for actor_action_id="
                f"{j.actor_action_id}; pipe is broken"
            )
            s.note = f"start row id={data['items'][0]['id']}"
