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

for _p in (_REPO_ROOT, _ANATOMY, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# CI splits the suite across runners (NOS_PYTEST_SHARD=k/N); unset = everything.
from _shard import pytest_collection_modifyitems  # noqa: E402,F401

# The estate clone's config.yml (nos_identity.operator_file) is the operator's live
# answer; a test that wants one sets NOS_ESTATE_DIR itself (test_readers_read_the_estate_config).
os.environ.setdefault("NOS_ESTATE_DIR", os.path.join(os.environ.get("TMPDIR", "/tmp"), "nos-pytest-no-estate"))

# The emergency halt is ONE file (~/.nos/halt) every scheduler obeys. A test that halts
# must never halt the live estate; a test that wants the file sets NOS_HALT_FILE itself.
os.environ.setdefault("NOS_HALT_FILE", os.path.join(os.environ.get("TMPDIR", "/tmp"), "nos-pytest-halt"))

# A test's playbook run must not write the operator's ~/.nos/ansible.log:
# after a leave it recreated ~/.nos, and its expected fatals read as a failed run.
os.environ.setdefault("ANSIBLE_LOG_PATH", os.path.join(
    os.environ.get("TMPDIR", "/tmp"), "nos-pytest-ansible.log"))
