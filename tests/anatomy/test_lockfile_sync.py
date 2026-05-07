"""Lockfile-sync gate (Anatomy 2026-05-07).

Catches composer.json / composer.lock drift BEFORE the operator's
playbook hits the `composer install` task and exits 4 with the cryptic
"lock file is not up to date" trace.

Triggered by:
    pytest tests/anatomy/test_lockfile_sync.py
And by the full CI run via the `pytest` job in .github/workflows/ci.yml.

Background — why this test exists:
    2026-05-07: I (Claude) edited files/anatomy/wing/composer.json to
    add dragonmantank/cron-expression without running `composer update`
    locally first. The lock file stayed at the old digest. The operator
    pulled, ran `ansible-playbook main.yml -K`, and got rc=4 deep in
    pazny.wing/tasks/main.yml — the SAME error this test detects in
    one second. The fix at source level is "always commit composer.lock
    alongside composer.json"; this gate makes the workflow self-policing.

Skipped (xfail-style) only when composer is not installed; the CI runner
ALWAYS has composer in PATH (we explicitly install it in the workflow).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.mark.skipif(
    shutil.which("composer") is None,
    reason="composer not in PATH — install via Homebrew or use the CI runner",
)
def test_wing_composer_lockfile_in_sync():
    """`composer validate --strict` exits 0 when json + lock match.

    Also catches: required PHP version mismatches, package-name typos,
    invalid version constraints. We deliberately use `--strict` so any
    warning becomes a failure; the CI gate is the right place for that.
    `--no-check-publish` skips the registry-publishability nag (we
    don't publish wing as a composer package).
    """
    wing_dir = os.path.join(_REPO, "files", "anatomy", "wing")
    if not os.path.isfile(os.path.join(wing_dir, "composer.lock")):
        pytest.skip("composer.lock missing — fresh-install path, not drift")

    proc = subprocess.run(
        ["composer", "validate", "--strict", "--no-check-publish"],
        cwd=wing_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"composer validate --strict failed (rc={proc.returncode}).\n"
        f"This means files/anatomy/wing/composer.json and composer.lock\n"
        f"are out of sync. Fix locally:\n"
        f"  cd files/anatomy/wing && composer update <package> --no-install\n"
        f"  git add composer.lock\n\n"
        f"--- composer stderr ---\n{proc.stderr}\n"
        f"--- composer stdout ---\n{proc.stdout}\n"
    )
