"""API unreachable -> retry 3x -> fail; wait_api_reachable respects timeout."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import time

import pytest
import responses
import requests

from module_utils.nos_authentik_client import (
    AuthentikApiError,
    NosAuthentikClient,
)


@responses.activate
def test_api_unreachable_retries_then_fails(api_base):
    """Connection errors should be retried exactly ``retries`` times."""
    # Register a ConnectionError on every request.
    responses.add(
        responses.GET,
        api_base + "/core/groups/",
        body=requests.exceptions.ConnectionError("boom"),
    )

    c = NosAuthentikClient(api_base, "tok", retries=3, backoff=0.001, timeout=1)
    with pytest.raises(AuthentikApiError) as exc_info:
        c.list_groups()
    assert "unreachable after 3 attempts" in str(exc_info.value)
    # ``responses`` records each attempt as a call.
    assert len(responses.calls) == 3


@responses.activate
def test_5xx_retries_then_fails(api_base):
    responses.add(responses.GET, api_base + "/core/groups/", status=500, body="oops")
    responses.add(responses.GET, api_base + "/core/groups/", status=502, body="oops")
    responses.add(responses.GET, api_base + "/core/groups/", status=503, body="oops")
    c = NosAuthentikClient(api_base, "tok", retries=3, backoff=0.001, timeout=1)
    with pytest.raises(AuthentikApiError) as exc_info:
        c.list_groups()
    assert exc_info.value.status_code == 503
    assert len(responses.calls) == 3


@responses.activate
def test_5xx_recovers_on_retry(api_base):
    responses.add(responses.GET, api_base + "/core/groups/", status=500)
    responses.add(responses.GET, api_base + "/core/groups/",
                  json={"results": [], "pagination": {"next": 0}}, status=200)
    c = NosAuthentikClient(api_base, "tok", retries=3, backoff=0.001, timeout=1)
    groups = c.list_groups()
    assert groups == []
    assert len(responses.calls) == 2


@responses.activate
def test_wait_api_reachable_respects_timeout(api_base):
    responses.add(
        responses.GET,
        api_base + "/core/users/me/",
        body=requests.exceptions.ConnectionError("never up"),
    )
    c = NosAuthentikClient(api_base, "tok", retries=3, backoff=0.001, timeout=1)
    t0 = time.monotonic()
    ok = c.wait_reachable(timeout_sec=0.5, poll_interval=0.05)
    elapsed = time.monotonic() - t0
    assert ok is False
    # Allow generous overhead but ensure we actually waited ~0.5s, not forever.
    assert 0.3 <= elapsed <= 3.0, "elapsed=%.3f" % (elapsed,)


@responses.activate
def test_wait_api_reachable_returns_true_on_2xx(api_base):
    responses.add(responses.GET, api_base + "/core/users/me/", json={"username": "akadmin"}, status=200)
    c = NosAuthentikClient(api_base, "tok", retries=1, backoff=0.001, timeout=1)
    assert c.wait_reachable(timeout_sec=2, poll_interval=0.05) is True


@responses.activate
def test_wait_api_reachable_returns_true_on_401(api_base):
    """Host is up but token is rejected — still counts as reachable."""
    responses.add(responses.GET, api_base + "/core/users/me/", json={"detail": "bad token"}, status=401)
    c = NosAuthentikClient(api_base, "bad-tok", retries=1, backoff=0.001, timeout=1)
    assert c.wait_reachable(timeout_sec=2, poll_interval=0.05) is True


@responses.activate
def test_404_raises_immediately_not_retried(api_base):
    responses.add(responses.GET, api_base + "/core/groups/123/", status=404)
    c = NosAuthentikClient(api_base, "tok", retries=3, backoff=0.001, timeout=1)
    with pytest.raises(AuthentikApiError) as exc_info:
        c.get("/core/groups/123/")
    assert exc_info.value.status_code == 404
    assert len(responses.calls) == 1  # no retry on 4xx
