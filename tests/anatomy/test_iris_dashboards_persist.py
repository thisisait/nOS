"""A placed dashboard lives in KEAP, per person (iris v3 B4, operator ruling Q1).

The pupil's workspaces.json is one Mac's; a dashboard the face or a second Mac must
see lives in the `iris-dashboards` DataTable. Its rows are written by the thalamus as
the person when they click Place, and listed back only to their owner. These gates
pin the definition, that a converge creates it, and the reader that counts it.
"""
from __future__ import annotations

import importlib.util
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
DEF = REPO / "state/keap-tables/iris-dashboards.table.yml"
CORE = REPO / "roles/pazny.keap/tasks/seed-core-tables.yml"
READER = REPO / "tools/thalamus-status.py"


def _columns() -> dict:
    d = yaml.safe_load(DEF.read_text(encoding="utf-8"))
    return {c["key"]: c for c in d["schema"]["columns"]}


def test_the_table_holds_owner_slug_name_lens_and_widgets():
    assert DEF.is_file(), f"no definition at {DEF.relative_to(REPO)}"
    cols = _columns()
    assert set(cols) == {"owner", "slug", "name", "lens", "widgets"}, sorted(cols)
    assert cols["owner"]["concept"] == "access.owner" and cols["owner"].get("required"), cols["owner"]
    assert cols["slug"].get("required") and cols["name"].get("required")
    assert cols["lens"]["kind"] == "json" and cols["widgets"]["kind"] == "json"


def test_every_person_may_reach_the_table_the_thalamus_filters_by_owner():
    """KEAP isolates no rows yet (visibility.ts: row __owner is a later change): the
    person must be able to read and write the table, and serve lists only their rows."""
    d = yaml.safe_load(DEF.read_text(encoding="utf-8"))
    assert d["visibility"] == "tier-users" and d["driver"] == "libsql"


def test_a_converge_creates_the_table():
    items = yaml.safe_load(CORE.read_text(encoding="utf-8"))[0]["loop"]
    hit = [i for i in items if i["slug"] == "iris-dashboards"]
    assert hit, "seed-core-tables.yml does not create iris-dashboards"
    assert "iris-dashboards.table.yml" in hit[0]["def"] and hit[0]["rows"] == []


def _reader():
    spec = importlib.util.spec_from_file_location("thalamus_status", READER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_reader_counts_dashboards_per_owner_or_says_unknown():
    r = _reader()
    down = r.judge_dashboards(None, "KEAP unreachable: refused")
    assert down["state"] == "UNKNOWN" and "KEAP unreachable" in down["detail"], down
    assert r.judge_dashboards([])["detail"] == "none yet"
    rows = [{"values": {"owner": "user:alice"}}, {"values": {"owner": "user:bob"}},
            {"values": {"owner": "user:alice"}}, {"values": {}}]
    got = r.judge_dashboards(rows)
    assert got["state"] == "OK" and got["detail"] == "user:alice 2, user:bob 1, (no owner) 1", got

