"""Add the repo root to sys.path so tests can import ``module_utils.*``.

pytest is intentionally run from anywhere — this conftest guarantees the
test file can locate the shared helpers regardless of cwd.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
# Anatomy A1 (2026-05-03): module_utils moved to files/anatomy/module_utils.
# Both paths added so `from module_utils.X import Y` resolves regardless of
# whether the module is still at the legacy location or already migrated.
_ANATOMY = os.path.join(_REPO_ROOT, "files", "anatomy")
for _p in (_REPO_ROOT, _ANATOMY):
    if _p not in sys.path:
        sys.path.insert(0, _p)
