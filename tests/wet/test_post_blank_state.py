"""Tier-2 wet-test — non-browser sections (6, 7, 9) of the checklist.

Mirrors `docs/tier2-wet-test-checklist.md` for the surfaces that are
deterministic and not browser-driven:

- Section 6 — GDPR Article 30 rows in `~/wing/wing.db`
- Section 7 — Bone `app.deployed` events in `~/.nos/events/playbook.jsonl`
- Section 9 — Smoke catalog runtime `state/smoke-catalog.runtime.yml`

Sections 2/3/4/5/8/11 are Playwright surfaces — see
`tests/e2e/tier2-wet-test.spec.ts`. Section 10 is a CLI invocation
(`tools/nos-smoke.py`) — Cowork runs directly.

These tests SKIP if the artifact isn't present (fresh worktree, pre-
blank state). Set `NOS_WET=1` to make missing artifacts hard-fail
instead — useful for post-blank verification runs.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

# Strict mode: zero/missing rows = FAIL. Default: SKIP. Mirrors conftest.py
# so the operator can flip the same env var for both wet artifact files
# AND empty-content cases (Bone events, GDPR rows, smoke catalog entries).
_STRICT = os.environ.get("NOS_WET") == "1"


def _missing(msg: str) -> None:
    """Skip pre-blank, fail under NOS_WET=1."""
    if _STRICT:
        pytest.fail(msg)
    pytest.skip(msg)


# ─── Section 6 — GDPR rows ────────────────────────────────────────────────

# Expected per-pilot legal_basis from `apps/<slug>.yml` gdpr blocks.
# Documenso = contract (signature service is processing under contract);
# the other two are legitimate_interests (security tool / mail client).
EXPECTED_LEGAL_BASIS = {
    "app_twofauth": "legitimate_interests",
    "app_roundcube": "legitimate_interests",
    "app_documenso": "contract",
}

# Allowed transfers_outside_eu = 0 for all three (EU-residency invariant).
# retention_days varies (twofauth = -1 ∞, roundcube = 365, documenso = 365)
# but we don't lock specific values — just sanity-check the integer shape.


class TestSection6_GdprRows:
    """Wet-test checklist Section 6 — three Article 30 rows in wing.db."""

    def test_table_exists(self, wing_db: Path) -> None:
        with sqlite3.connect(wing_db) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='gdpr_processing'"
            ).fetchone()
        assert row is not None, (
            "gdpr_processing table missing — Wing schema didn't migrate. "
            "Check `~/.nos/ansible.log` for Wing migration errors."
        )

    def test_three_app_rows(self, wing_db: Path) -> None:
        with sqlite3.connect(wing_db) as conn:
            ids = [
                r[0]
                for r in conn.execute(
                    "SELECT id FROM gdpr_processing "
                    "WHERE id LIKE 'app_%' ORDER BY id"
                )
            ]
        if not ids:
            _missing(
                "gdpr_processing has zero app_* rows — pre-Tier-2-deploy "
                "state, or apps_runner GDPR upsert post-hook failed. "
                "Check `grep 'OK upserted gdpr_processing' ~/.nos/ansible.log`."
            )
        missing = set(EXPECTED_LEGAL_BASIS) - set(ids)
        assert not missing, (
            f"Missing GDPR rows: {sorted(missing)}. Got {sorted(ids)}."
        )

    @pytest.mark.parametrize("app_id,expected", EXPECTED_LEGAL_BASIS.items())
    def test_legal_basis(
        self, wing_db: Path, app_id: str, expected: str
    ) -> None:
        with sqlite3.connect(wing_db) as conn:
            row = conn.execute(
                "SELECT legal_basis, transfers_outside_eu, retention_days "
                "FROM gdpr_processing WHERE id = ?",
                (app_id,),
            ).fetchone()
        assert row is not None, f"{app_id} GDPR row missing"
        legal_basis, transfers, retention = row
        assert legal_basis == expected, (
            f"{app_id} legal_basis={legal_basis!r} (expected {expected!r}); "
            f"check apps/{app_id.removeprefix('app_')}.yml gdpr.legal_basis"
        )
        assert transfers == 0, (
            f"{app_id} transfers_outside_eu={transfers} — EU-residency "
            "invariant violated"
        )
        assert isinstance(retention, int), (
            f"{app_id} retention_days={retention!r} not int (-1 = ∞ allowed)"
        )


# ─── Section 7 — Bone `app.deployed` events ──────────────────────────────


def _load_app_deployed(events_path: Path) -> list[dict]:
    """Tail-load every `app.deployed` event from the JSONL (full file).

    The file is append-only; one blank typically adds 3 events (one per
    pilot). Earlier blanks leave older events in place — we filter on
    the most recent run_id below.
    """
    out: list[dict] = []
    with events_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue  # corrupt line — Bone never wrote one historically
            if ev.get("type") == "app.deployed":
                out.append(ev)
    return out


class TestSection7_BoneEvents:
    """Wet-test checklist Section 7 — three `app.deployed` events."""

    def test_jsonl_has_app_deployed_events(
        self, events_jsonl: Path
    ) -> None:
        events = _load_app_deployed(events_jsonl)
        if not events:
            _missing(
                "Zero `app.deployed` events in playbook.jsonl — pre-Tier-2 "
                "or Bone delivery broken. Check "
                "`grep 'Bone events delivery' ~/.nos/ansible.log`."
            )

    def test_latest_run_covers_all_three_pilots(
        self, events_jsonl: Path
    ) -> None:
        events = _load_app_deployed(events_jsonl)
        if not events:
            pytest.skip("no app.deployed events — covered by previous test")

        # Take the most recent run_id and filter; that's the "this blank"
        # cohort. (Older runs from previous blanks stay in the file.)
        latest_run = events[-1].get("run_id")
        assert latest_run, "latest event missing run_id"
        latest = [e for e in events if e.get("run_id") == latest_run]

        app_ids = {e.get("app_id") for e in latest}
        expected = {"twofauth", "roundcube", "documenso"}
        missing = expected - app_ids
        assert not missing, (
            f"Latest run_id={latest_run} missing app_deployed for "
            f"{sorted(missing)}. Got: {sorted(app_ids)}"
        )

    def test_event_shape(self, events_jsonl: Path) -> None:
        events = _load_app_deployed(events_jsonl)
        if not events:
            pytest.skip("no app.deployed events")
        ev = events[-1]
        # Required fields per docs/tier2-wet-test-checklist.md §7
        for field in (
            "ts",
            "run_id",
            "type",
            "source",
            "app_id",
            "fqdn",
            "category",
            "auth_mode",
            "stack",
            "tier",
        ):
            assert field in ev, f"`{field}` missing from app.deployed event"
        assert ev["type"] == "app.deployed"
        assert ev["source"] == "apps_runner"
        assert ev["stack"] == "apps"
        assert ev["tier"] == 2
        assert ev["auth_mode"] in {"proxy", "oauth2", "none"}


# ─── Section 9 — Smoke catalog runtime ───────────────────────────────────


def _load_runtime_catalog(path: Path) -> dict:
    # Lazy yaml import so missing-pyyaml doesn't break test collection.
    yaml = pytest.importorskip("yaml")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


class TestSection9_SmokeCatalog:
    """Wet-test checklist Section 9 — runtime catalog has 3 Tier-2 entries."""

    def test_file_exists_and_parses(self, smoke_catalog: Path) -> None:
        data = _load_runtime_catalog(smoke_catalog)
        assert isinstance(data, dict), (
            f"{smoke_catalog} did not parse to a mapping"
        )

    def test_smoke_endpoints_block_present(
        self, smoke_catalog: Path
    ) -> None:
        data = _load_runtime_catalog(smoke_catalog)
        endpoints = data.get("smoke_endpoints")
        assert isinstance(endpoints, list), (
            "smoke_endpoints missing or not a list — "
            "apps_runner post-hook didn't extend the catalog"
        )

    def test_three_app_entries(self, smoke_catalog: Path) -> None:
        data = _load_runtime_catalog(smoke_catalog)
        endpoints = data.get("smoke_endpoints") or []
        ids = {e.get("id") for e in endpoints if isinstance(e, dict)}
        expected = {"app_twofauth", "app_roundcube", "app_documenso"}
        missing = expected - ids
        assert not missing, (
            f"smoke_endpoints missing entries: {sorted(missing)}; got "
            f"{sorted(ids)}. Re-run apps_runner; "
            "check `grep 'Extend smoke catalog' ~/.nos/ansible.log`."
        )

    def test_app_entries_well_formed(
        self, smoke_catalog: Path, pilot: str
    ) -> None:
        data = _load_runtime_catalog(smoke_catalog)
        endpoints = data.get("smoke_endpoints") or []
        entry = next(
            (
                e
                for e in endpoints
                if isinstance(e, dict) and e.get("id") == f"app_{pilot}"
            ),
            None,
        )
        if entry is None:
            pytest.skip(f"app_{pilot} not in smoke_endpoints")
        url = entry.get("url", "")
        assert url.startswith("https://"), (
            f"app_{pilot}.url={url!r} not https://"
        )
        assert pilot in url, (
            f"app_{pilot}.url={url!r} does not contain slug {pilot!r}"
        )
        assert entry.get("tier") == 2, (
            f"app_{pilot}.tier={entry.get('tier')!r} (expected 2)"
        )
        expect = entry.get("expect")
        assert isinstance(expect, list) and expect, (
            f"app_{pilot}.expect={expect!r} (expected non-empty list of "
            "acceptable HTTP codes)"
        )
        assert all(isinstance(c, int) for c in expect), (
            f"app_{pilot}.expect contains non-int: {expect!r}"
        )
