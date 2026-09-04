"""/hub must not read "all clear" while the estate is not.

MEASURED 2026-08-31: the page probed 33 services over HTTP, called every one
`up`, and said nothing at all while two Pulse jobs had been failing for half a
day and eight notifications sat unread. Health there is an HTTP probe; the page
knew nothing its own database already held.

Both facts live in wing.db and both already had a repository — `PulseRepository`
and `NotificationRepository`. The page simply never asked.

WHAT THIS CHECKS, AND WHY IT IS A CROSS-CHECK. The interesting half is not that
a tile renders; it is that a DECLARED FINDINGS CODE IS NOT A FAILURE. A job
that exits 3 to say "I found something" has not failed, and the same defect has
now been found twice in this estate in two languages — `_source_pulse_runs`
(python, fixed 2026-08-31) and `PulseRepository::runSummaries`'s `fails_window`
(php, fixed the same day). So this recomputes the answer INDEPENDENTLY in
python, straight from wing.db, and asserts the number the page renders agrees.
Either side drifting fails the test, which is the only arrangement that catches
a second copy of a rule going stale.

SCOPE IS DELIBERATE. The tile counts what Wing knows first-hand: failing Pulse
jobs + unread notifications. `tools/red-status.py` also reports CI and
Dependabot via `gh`, which Wing has no business shelling out to — so the tile
names its scope rather than implying a total that would disagree with the
reader everyone quotes.

Skips (never passes) when Wing is not reachable: an unrendered page is an
unknown, not a clean one.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sqlite3
import urllib.error
import urllib.request

import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
from _ledger_open import open_ledger_ro  # noqa: E402 — after REPO is known
WING = os.environ.get("NOS_WING_URL", "http://127.0.0.1:9000")


def _secret(name: str) -> str:
    try:
        import yaml
        store = yaml.safe_load((pathlib.Path.home() / ".nos" / "secrets.yml").read_text()) or {}
        return str(store.get(name) or "")
    except Exception:                                   # noqa: BLE001
        return ""


def _hub_html() -> str:
    token = _secret("wing_edge_token")
    if not token:
        pytest.skip("no wing_edge_token in ~/.nos/secrets.yml")
    req = urllib.request.Request(f"{WING}/hub", headers={
        "X-Wing-Edge-Token": token,
        "X-Authentik-Username": "pazny",
        "X-Authentik-Groups": "nos-providers|nos-admins",
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"Wing is not answering: {exc}")


def _expected_red() -> tuple[int, list[str]]:
    """The same question, asked of the database directly.

    Read WAL-aware, NOT `immutable=1` (fixed 2026-09-04): immutable reads the
    main db file and IGNORES the -wal, while the live page reads WAL-included.
    When reconcile-inbox has just marked rows superseded in the WAL (not yet
    checkpointed), the immutable read is systematically stale-HIGH and the page
    fresh-LOW — the page's number falls BELOW the [before, after] interval and
    the interval defence cannot catch it (both bounds are stale). Measured: an
    `8 vs 17` failure that passed on re-run once the WAL checkpointed.

    Via `_ledger_open.open_ledger_ro`, not a bare `mode=ro`: measured
    2026-09-04, `mode=ro` FAILS 'unable to open' on a db whose -wal is absent
    (checkpointed) — the exact trap the ledger reader exists to handle: mode=ro
    while a WAL is live, immutable snapshot when it is not (which is then the
    checkpointed-in current state, also what the page sees)."""
    db = pathlib.Path(os.environ.get(
        "WING_DB_PATH", str(pathlib.Path.home() / "wing/app/data/wing.db")))
    if not db.is_file():
        pytest.skip("no wing.db on this host")
    conn, how = open_ledger_ro(db)
    if conn is None:
        pytest.skip(f"wing.db not readable: {how}")
    conn.row_factory = sqlite3.Row
    try:
        findings: dict[str, set[int]] = {}
        for row in conn.execute(
                "SELECT id, findings_exit_codes FROM pulse_jobs "
                "WHERE findings_exit_codes IS NOT NULL"):
            try:
                codes = json.loads(row["findings_exit_codes"] or "[]")
            except (TypeError, ValueError):
                continue
            if isinstance(codes, list):
                findings[row["id"]] = {int(c) for c in codes if str(c).lstrip("-").isdigit()}
        failing = []
        for row in conn.execute(
                "SELECT job_id, exit_code FROM (SELECT job_id, exit_code, run_id, "
                "ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY fired_at DESC, run_id DESC) rn "
                "FROM pulse_runs) WHERE rn = 1 AND exit_code IS NOT NULL AND exit_code != 0"):
            if int(row["exit_code"]) in findings.get(row["job_id"], set()):
                continue
            failing.append(row["job_id"])
        # The predicate mirrors NotificationRepository::countUnread exactly —
        # unread AND not superseded. A first draft guessed `read_at`, which is
        # not a column, and the test SKIPPED. A skip is not a pass, and a
        # cross-check that quietly opts out is worse than no cross-check.
        unread = conn.execute(
            "SELECT COUNT(*) n FROM notifications "
            "WHERE target_actor_id = 'operator' "
            "  AND wing_inbox_read_at IS NULL AND superseded_at IS NULL").fetchone()["n"]
        return len(failing) + int(unread), failing
    except sqlite3.OperationalError as exc:
        pytest.skip(f"wing.db could not be read: {exc}")
    finally:
        conn.close()


def test_the_hub_renders_and_carries_the_tile() -> None:
    html = _hub_html()
    assert "sys-card" in html, "the hub did not render its cards at all"
    assert "Estate red" in html, (
        "no estate-red tile: /hub shows HTTP health only, so a service can be "
        "up while its nightly job is dead and the page still reads all clear")


def test_the_number_agrees_with_the_database() -> None:
    """Both sides move — a converge writes notifications while this runs — so
    the database is read either side of the page fetch and the rendered number
    must fall in that interval. Sampling once gave a 13-vs-12 that was pure
    timing (MEASURED 2026-09-02), and a cross-check that fails on timing alone
    is one everybody learns to ignore."""
    before, _ = _expected_red()
    html = _hub_html()
    after, failing = _expected_red()
    found = re.search(r'Estate red</div>\s*<div class="value"[^>]*>(\d+)<', html)
    assert found, "the tile renders no number"
    rendered = int(found.group(1))
    lo, hi = min(before, after), max(before, after)
    assert lo <= rendered <= hi, (
        f"the page says {rendered} and the database said {before} before the "
        f"fetch and {after} after (failing jobs: {failing or 'none'}). The two "
        "sides of this count have drifted — most likely one of them started "
        "treating a declared findings exit code as a failure.")


def test_a_findings_code_is_not_counted_as_a_failure() -> None:
    """The population guard. If no job declares findings codes, the assertion
    above is real but weak, and this says so rather than passing quietly."""
    db = pathlib.Path(os.environ.get(
        "WING_DB_PATH", str(pathlib.Path.home() / "wing/app/data/wing.db")))
    if not db.is_file():
        pytest.skip("no wing.db on this host")
    conn = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
    try:
        n = conn.execute("SELECT COUNT(*) FROM pulse_jobs "
                         "WHERE findings_exit_codes IS NOT NULL").fetchone()[0]
    except sqlite3.OperationalError as exc:
        pytest.skip(f"wing.db could not be read: {exc}")
    finally:
        conn.close()
    assert n >= 1, (
        "no job declares findings_exit_codes on this host, so the agreement "
        "test above cannot distinguish the two rules — it is passing on a "
        "population where they happen to be identical")
