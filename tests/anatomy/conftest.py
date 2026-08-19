"""Shared scaffolding for anatomy tests.

Adds files/anatomy/pulse/ to sys.path so ``from pulse.<module>`` resolves
without an editable install, and this directory itself so the shared
``service_edge_probe`` helper resolves from the two gates that read it.
"""

from __future__ import annotations

import os
import sys

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
