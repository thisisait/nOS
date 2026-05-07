#!/usr/bin/env python3
"""Sweep orphaned ``nos-tester-e2e-*`` users + Wing tokens (A13.6).

This is the belt-and-suspenders cleanup for the ephemeral test-identity
layer. The primary cleanup paths are:
  1. pytest fixture teardown (yield → teardown_tester)
  2. conftest atexit hook (crashed pytest process)

This script is the THIRD line of defense — runs on a schedule (Pulse cron)
and deletes any tester identity older than the threshold. Useful when:
  * pytest gets SIGKILL'd by the OS / runaway
  * the developer Ctrl+C's mid-test (atexit doesn't always fire)
  * Authentik was unreachable during fixture teardown

Usage:
    python3 sweep-orphan-testers.py                 # delete >1h old
    python3 sweep-orphan-testers.py --dry-run       # report only
    python3 sweep-orphan-testers.py --max-age 0     # delete everything

Wired up via the future ``e2e-harness-base`` plugin's pulse job (TBD).
For now: invoke manually or stick in a cron.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


def _setup_imports() -> None:
    """Add the repo root to sys.path so the test-only lib is importable from
    a script that lives outside the test tree."""
    here = Path(__file__).resolve()
    repo_root = here.parents[3]  # files/anatomy/scripts/ → repo root
    sys.path.insert(0, str(repo_root))


def main() -> int:
    _setup_imports()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-age", type=int, default=3600,
        help="delete users older than N seconds (default: 3600 = 1h)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="list what would be deleted without making changes",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="machine-readable output (for Pulse/cron consumption)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s sweep-orphan-testers %(levelname)s %(message)s",
    )

    try:
        from tests.e2e.lib.tester_identity import sweep_orphans
        from tests.e2e.lib.authentik_admin import AuthentikAdmin, AuthentikAdminError
    except ImportError as exc:
        print(f"FATAL: cannot import tester identity lib: {exc}", file=sys.stderr)
        return 2

    try:
        admin = AuthentikAdmin.from_env()
    except AuthentikAdminError as exc:
        print(f"FATAL: cannot reach Authentik: {exc}", file=sys.stderr)
        return 2

    result = sweep_orphans(
        max_age_seconds=args.max_age,
        admin=admin,
        dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(result))
    else:
        print(
            f"orphan-sweep max_age={args.max_age}s dry_run={args.dry_run}: "
            f"found={result['found']} deleted={result['deleted']} "
            f"skipped={result['skipped']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
