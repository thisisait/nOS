"""Shared scaffolding for anatomy tests.

Adds files/anatomy/pulse/ to sys.path so ``from pulse.<module>`` resolves
without an editable install, and this directory itself so the shared
``service_edge_probe`` helper resolves from the two gates that read it.
"""

from __future__ import annotations

import copy
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
_PULSE = os.path.join(_REPO, "files", "anatomy", "pulse")

for _p in (_REPO, _PULSE, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# The environment contract (2026-08-19): an environment that declares tools in
# NOS_TEST_PROVIDES and lacks one ABORTS here, at import, before any test runs;
# every skip is counted and printed as its own outcome in the terminal summary.
# Pinned (failure branch exercised for real) by test_absence_is_counted.py.
from _environment_contract import (  # noqa: E402
    enforce_contract,
    pytest_terminal_summary,  # noqa: F401 — re-exported pytest hook
)

enforce_contract()

# The offline boundary (2026-10-02, after the RustFS write incident): armed here
# at import so even collection-time code sees no ~/.nos, no docker, no live port.
import _live_guard  # noqa: E402

_live_guard.arm()


def pytest_configure(config):
    config.addinivalue_line(
        "markers", f"{_live_guard.MARK}: reads ~/.nos, docker, or a loopback service; "
        f"skipped unless {_live_guard.ENV}=1, which lifts the offline boundary for it")
    config.addinivalue_line(
        "markers",
        f"{_live_guard.DOCKER_CLI}: docker compose config over a local -f file only; "
        "no daemon and no estate — the other offline doors stay shut")


@pytest.fixture(autouse=True)
def _offline_boundary(request):
    if request.node.get_closest_marker(_live_guard.MARK):
        if not _live_guard.live_run():
            pytest.skip(
                f"{_live_guard.ENV} unset — @pytest.mark.live runs only with {_live_guard.ENV}=1")
        with _live_guard.lifted():
            yield
    elif request.node.get_closest_marker(_live_guard.DOCKER_CLI):
        with _live_guard.docker_cli():
            yield
    else:
        yield


class _Estate:
    """Estate builds made once per session (a keap docs walk is ~7 s). `once` returns a
    deep copy each call, so a test that mutates its result cannot reach another test.
    A key names ONE build of the committed tree: reuse it only for an identical call."""

    def __init__(self):
        self._memo: dict = {}

    def once(self, key: str, build):
        if key not in self._memo:
            self._memo[key] = build()
        return copy.deepcopy(self._memo[key])


@pytest.fixture(scope="session")
def estate() -> _Estate:
    return _Estate()
