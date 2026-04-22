"""Shared pytest config for coexistence tests.

Injects the repository root into ``sys.path`` so that ``library/`` and
``module_utils/`` can be imported as regular packages from the tests,
without needing an editable install.
"""

from __future__ import annotations

import os
import sys

# tests/coexistence/conftest.py  →  tests/  →  repo root
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
