"""Shared scaffolding for Tier-2 app parser tests.

Adds the repo root to sys.path so ``module_utils.nos_app_parser`` is
importable without Ansible's plugin loader.
"""

from __future__ import absolute_import, division, print_function

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# Anatomy A1 (2026-05-03): module_utils moved to files/anatomy/module_utils.
ANATOMY = os.path.join(ROOT, "files", "anatomy")
for _p in (ROOT, ANATOMY):
    if _p not in sys.path:
        sys.path.insert(0, _p)
