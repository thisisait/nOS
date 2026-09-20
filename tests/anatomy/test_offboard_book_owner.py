"""First book_owner offboard door — dry-run planner + confirm-slug stub.

RETRO-RED: tools/offboard-book-owner.py did not exist; importing it fails on
the pre-tool tree. Parallel to email-keyed gdpr-forget, keyed on a FIRM slug.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "offboard-book-owner.py"
ALFA = "synthetic-client-alfa"
BETA = "synthetic-client-beta"


def _load():
    spec = importlib.util.spec_from_file_location("offboard_book_owner", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_retro_red_tool_exists():
    assert TOOL.is_file(), "offboard-book-owner.py is the exclusive door"


def _tree(tmp: pathlib.Path, slug: str) -> pathlib.Path:
    base = tmp / "tenants" / "consultant" / "users" / "u1" / "inbox" / "accounting" / slug
    for leaf in ("incoming", "extracts", "processed"):
        (base / leaf).mkdir(parents=True)
    (base / "extracts" / "alfa.extract.json").write_text("{}", encoding="utf-8")
    (base / "incoming" / "inv.pdf").write_text("x", encoding="utf-8")
    return base


def _rows():
    return {
        "invoice": [
            {"slug": "inv-alfa", "book_owner": ALFA, "seller": ALFA, "buyer": "synthetic-alfa-customer"},
            {"slug": "inv-beta", "book_owner": BETA, "seller": BETA, "buyer": "synthetic-beta-customer"},
            {"slug": "inv-beta-from-alfa", "book_owner": BETA, "seller": ALFA, "buyer": BETA},
        ],
        "journal-entry": [
            {"slug": "je-alfa", "source": "inv-alfa"},
            {"slug": "je-beta", "source": "inv-beta"},
        ],
        "invoice-line": [
            {"slug": "line-alfa", "invoice": "inv-alfa"},
            {"slug": "line-beta", "invoice": "inv-beta"},
        ],
        "posting": [
            {"slug": "p-alfa-1", "entry": "je-alfa", "account": "acc-311-alfa"},
            {"slug": "p-beta-1", "entry": "je-beta", "account": "acc-311-beta"},
        ],
        "pending-invoice-verify": [
            {"slug": "piv-alfa", "sidecar_id": "alfa.extract.json", "fields": {"x": {"value": ALFA}}},
            {"slug": "piv-other", "sidecar_id": "other.extract.json", "fields": {"x": {"value": BETA}}},
        ],
        "account": [
            {"slug": "acc-311", "code": "311", "name": "shared"},
            {"slug": "acc-311-alfa", "code": "311-alfa", "party": ALFA},
            {"slug": "acc-321-alfa", "code": "321-alfa", "party": ALFA},
            {"slug": "acc-311-beta", "code": "311-beta", "party": BETA},
        ],
        "party-tax-identity": [
            {"slug": "tax-alfa", "party": ALFA},
            {"slug": "tax-beta", "party": BETA},
        ],
        "party-address": [{"slug": "addr-alfa", "party": ALFA}],
        "party-contact": [{"slug": "contact-alfa", "party": ALFA}],
        "party": [
            {"slug": ALFA, "legal_name": "Alfa"},
            {"slug": BETA, "legal_name": "Beta"},
        ],
    }


def test_dry_run_prints_plan_and_exits_0(tmp_path):
    _tree(tmp_path, ALFA)
    rows_path = tmp_path / "rows.json"
    rows_path.write_text(json.dumps(_rows()), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(TOOL), ALFA, "--data-root", str(tmp_path),
         "--rows-json", str(rows_path)],
        capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    plan = json.loads(r.stdout)
    assert plan["mode"] == "DRY-RUN"
    keap = {(s["table"], s.get("slug")) for s in plan["keap"]}
    assert ("invoice", "inv-alfa") in keap
    assert ("invoice", "inv-beta") not in keap
    assert ("journal-entry", "je-alfa") in keap
    assert ("invoice-line", "line-alfa") in keap
    assert ("invoice-line", "line-beta") not in keap
    assert ("posting", "p-alfa-1") in keap
    assert ("account", "acc-311-alfa") in keap
    assert ("account", "acc-311") not in keap
    assert ("pending-invoice-verify", "piv-alfa") in keap
    assert plan["espo"]["method"] == "manual"
    assert plan["espo"]["marker"] == f"nos:party:{ALFA}"
    assert any("rmtree" in str(x) and ALFA in x["path"] for x in plan["filesystem"])
    assert (tmp_path / "tenants/consultant/users/u1/inbox/accounting" / ALFA / "incoming").is_dir()
    bodies = [s["path"] for s in plan["keap"] if s.get("method") == "DELETE"]
    assert any(p.endswith("/invoice/rows/inv-alfa") for p in bodies)


def test_planner_does_not_wipe_beta_and_retains_shared_party(tmp_path):
    mod = _load()
    planned = mod.plan(ALFA, _rows(), data_root=tmp_path)
    slugs = {s["slug"] for s in planned["keap"] if s.get("method") == "DELETE"}
    assert "inv-beta" not in slugs and "je-beta" not in slugs and "p-beta-1" not in slugs
    party_steps = [s for s in planned["keap"] if s["table"] == "party"]
    assert party_steps and party_steps[0]["action"] == "retain"


def test_confirm_requires_matching_slug(monkeypatch):
    mod = _load()
    monkeypatch.delenv("NOS_OFFBOARD_CONFIRM", raising=False)
    assert mod.main([ALFA, "--confirm", BETA]) == 2
    monkeypatch.setenv("NOS_OFFBOARD_CONFIRM", BETA)
    assert mod.main([ALFA]) == 2
    monkeypatch.setenv("NOS_OFFBOARD_CONFIRM", ALFA)
    assert mod.main([ALFA, "--confirm", BETA]) == 2


def test_bad_slug_refuses():
    mod = _load()
    assert mod.main(["Alfa"]) == 2
    assert mod.main(["../etc"]) == 2
    assert mod.main(["a"]) == 2


def test_confirm_rmtree_and_keap_delete(tmp_path, monkeypatch):
    mod = _load()
    live = _tree(tmp_path, ALFA)
    fixture = REPO / "state" / "fixtures"
    monkeypatch.setenv("NOS_OFFBOARD_CONFIRM", ALFA)
    deleted = []
    monkeypatch.setattr(mod, "delete_row", lambda t, s: deleted.append((t, s)))
    rows_path = tmp_path / "rows.json"
    rows_path.write_text(json.dumps(_rows()), encoding="utf-8")
    rc = mod.main([ALFA, "--confirm", ALFA, "--data-root", str(tmp_path),
                   "--rows-json", str(rows_path)])
    assert rc == 0
    assert not (live / "incoming").exists()
    assert fixture.is_dir()
    assert ("invoice", "inv-alfa") in deleted
    assert ("invoice-line", "line-alfa") in deleted
    assert ("posting", "p-alfa-1") in deleted
    assert ("invoice", "inv-beta") not in deleted
    assert deleted.index(("posting", "p-alfa-1")) < deleted.index(("invoice", "inv-alfa"))
    planned = mod.plan(ALFA, {}, data_root=REPO / "state" / "fixtures")
    assert planned["filesystem"] == []


def test_party_last_when_no_foreign_refs():
    mod = _load()
    rows = {
        "invoice": [{"slug": "inv-a", "book_owner": ALFA}],
        "journal-entry": [{"slug": "je-a", "source": "inv-a"}],
        "posting": [{"slug": "p-a", "entry": "je-a", "account": "acc-311-alfa"}],
        "account": [{"slug": "acc-311-alfa", "code": "311-alfa", "party": ALFA}],
        "party": [{"slug": ALFA}],
        "pending-invoice-verify": [],
        "party-tax-identity": [],
        "party-address": [],
        "party-contact": [],
    }
    planned = mod.plan(ALFA, rows)
    deletes = [s for s in planned["keap"] if s.get("method") == "DELETE"]
    assert deletes[-1]["table"] == "party" and deletes[-1]["slug"] == ALFA
    tables = [s["table"] for s in deletes]
    assert tables.index("posting") < tables.index("journal-entry") < tables.index("invoice")
    assert "live KEAP DELETE not proven" not in planned["unsolved"]
    assert any("Art-17" in u for u in planned["unsolved"])
    assert planned["audit_post"]["body"]["request_type"] == "erase"
