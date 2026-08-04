"""The 1.x → 2.x payload deltas, pinned where CI can reach them.

Each assertion below corresponds to a REFUSAL measured on 2026-08-04 against a
throwaway `louislam/uptime-kuma:2.2.1` container. They are not guesses about
what Kuma 2 might want; they are the errors it actually returned, one per
missing field:

  conditions absent          → SQLITE_CONSTRAINT: NOT NULL constraint failed:
                               monitor.conditions
  accepted_statuscodes absent
    on a NON-http monitor    → Cannot read properties of undefined
                               (reading 'every')
  analyticsType key absent   → Invalid analytics type
                               (the handler tests `!== null`, and an ABSENT key
                                is `undefined`, which takes the invalid branch —
                                so omitting it is NOT the same as leaving it
                                unset)
  imgDataUrl null            → Cannot read properties of null
                               (reading 'startsWith')

WHY A GATE RATHER THAN A COMMENT. The live proof needs Docker and a fresh
container, so it cannot run in CI; what CI can hold is the shape those
experiments produced. Without this, the next person to tidy `monitor_payload`
would drop a field that looks redundant — `conditions: []` reads like a no-op —
and the failure would surface only at converge time, on the one service whose
whole job is to notice failures.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
KUMA2 = REPO / "roles/pazny.uptime_kuma/files/kuma2.py"


@pytest.fixture(scope="module")
def kuma2():
    spec = importlib.util.spec_from_file_location("kuma2_under_test", KUMA2)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kuma2_under_test"] = mod
    spec.loader.exec_module(mod)
    try:
        yield mod
    finally:
        sys.modules.pop("kuma2_under_test", None)


# --- monitors --------------------------------------------------------------

def test_every_monitor_carries_conditions(kuma2):
    """NOT NULL on 2.x. An empty list is the correct 'no extra conditions'."""
    for spec in (
        {"name": "a", "type": "http", "url": "https://x"},
        {"name": "b", "type": "tcp", "hostname": "127.0.0.1", "port": 6379},
        {"name": "c", "type": "ping", "hostname": "127.0.0.1"},
    ):
        payload = kuma2.monitor_payload(spec)
        assert "conditions" in payload, (
            f"{spec['type']} monitor has no `conditions`; the insert dies on "
            f"NOT NULL constraint failed: monitor.conditions"
        )
        assert isinstance(payload["conditions"], list)


def test_every_monitor_carries_accepted_statuscodes(kuma2):
    """Read for EVERY type on 2.x, not just http — v1 sent it only for http."""
    for spec in (
        {"name": "a", "type": "http", "url": "https://x"},
        {"name": "b", "type": "tcp", "hostname": "127.0.0.1", "port": 6379},
        {"name": "c", "type": "docker", "docker_container": "x"},
    ):
        payload = kuma2.monitor_payload(spec)
        assert payload.get("accepted_statuscodes"), (
            f"{spec['type']} monitor has no `accepted_statuscodes`; Kuma 2 "
            f"calls .every() on it regardless of type and refuses with "
            f"'Cannot read properties of undefined'"
        )


def test_tcp_is_translated_to_port_without_losing_the_address(kuma2):
    """The alias must not outrun the branch that fills in host and port."""
    payload = kuma2.monitor_payload(
        {"name": "Redis TCP", "type": "tcp", "hostname": "10.0.0.5", "port": 6379})
    assert payload["type"] == "port", "Kuma has always called a TCP check 'port'"
    assert payload["hostname"] == "10.0.0.5"
    assert payload["port"] == 6379


def test_a_spec_that_already_says_port_still_gets_an_address(kuma2):
    """The regression the alias table invites.

    Translating the type field while branching on the UNtranslated word drops
    hostname/port for any spec written in Kuma's own vocabulary — silently, and
    only for specs nobody in this repo writes today.
    """
    payload = kuma2.monitor_payload(
        {"name": "x", "type": "port", "hostname": "10.0.0.5", "port": 5432})
    assert payload["hostname"] == "10.0.0.5"
    assert payload["port"] == 5432


def test_http_keeps_its_url_and_tls_posture(kuma2):
    payload = kuma2.monitor_payload(
        {"name": "x", "type": "http", "url": "https://x", "expiry_notification": True})
    assert payload["url"] == "https://x"
    assert payload["ignoreTls"] is True
    assert payload["expiryNotification"] is True


# --- status page -----------------------------------------------------------

def test_the_analytics_keys_are_present_and_null(kuma2):
    """Absent is NOT the same as null here, and that is the whole point.

    `config.analyticsType !== null && !valid.includes(config.analyticsType)` —
    an absent key evaluates `undefined !== null` as true and then fails the
    membership test, so the save is refused with "Invalid analytics type".
    """
    cfg = kuma2.status_page_config("nos", "nOS Service Status")
    for key in ("analyticsType", "analyticsId", "analyticsScriptUrl"):
        assert key in cfg, (
            f"{key} is absent; Kuma 2 reads that as `undefined`, takes the "
            f"invalid branch, and refuses the save with 'Invalid analytics type'"
        )
    assert cfg["analyticsType"] is None


def test_the_status_page_is_published_and_identified(kuma2):
    cfg = kuma2.status_page_config("nos", "nOS Service Status", "desc")
    assert cfg["slug"] == "nos"
    assert cfg["title"] == "nOS Service Status"
    assert cfg["description"] == "desc"
    assert cfg["published"] is True, (
        "an unpublished status page returns 404 to everyone, which looks "
        "exactly like a routing fault"
    )


def test_the_v1_analytics_field_is_gone(kuma2):
    """Leaving it behind is harmless but misleading — 2.x ignores it."""
    cfg = kuma2.status_page_config("nos", "t")
    assert "googleAnalyticsId" not in cfg, (
        "googleAnalyticsId is the 1.x spelling; 2.x replaced it with the "
        "analyticsType/analyticsId/analyticsScriptUrl trio"
    )
