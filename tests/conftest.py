"""Repo-wide pytest scaffolding.

Centralizes the sys.path injection that several per-directory conftest.py
files have been duplicating. After Anatomy A1 (2026-05-03), the canonical
home for ``library/`` and ``module_utils/`` is ``files/anatomy/``; this
conftest adds BOTH the repo root and ``files/anatomy/`` to sys.path so
imports of ``module_utils.X`` continue to resolve regardless of which
test subdir imports them.

Per-directory conftest.py files retain their own additions for backwards
compatibility — having the same path inserted twice is a no-op (the
guard ``if _p not in sys.path`` handles it).
"""

from __future__ import absolute_import, division, print_function

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir))
_ANATOMY = os.path.join(_REPO_ROOT, "files", "anatomy")

for _p in (_REPO_ROOT, _ANATOMY):
    if _p not in sys.path:
        sys.path.insert(0, _p)
