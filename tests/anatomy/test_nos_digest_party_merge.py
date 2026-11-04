"""party-merge: a forked party folds into its winner (nos_digest.merge_party).

The store below enforces onDelete:restrict the way KEAP does: deleting a row that a
rowRef cell still points at is refused. The edge set is read from the real table
defs (state/keap-tables), so a new table referencing party is covered by the walk.
"""
import copy
import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TABLES = REPO / "state" / "keap-tables"


def _nd():
    spec = importlib.util.spec_from_file_location(
        "nos_digest", REPO / "files" / "anatomy" / "module_utils" / "nos_digest.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ND = _nd()

SEED = {
    "party": [{"slug": "party-L"}, {"slug": "party-W"}],
    "party-tax-identity": [{"slug": "tax-L", "party": "party-L", "scheme": "ICO", "value": "1"},
                           {"slug": "tax-W", "party": "party-W", "scheme": "ICO", "value": "1"}],
    "party-contact": [{"slug": "mail-L", "party": "party-L", "value": "a@example.test"}],
    "repo": [{"slug": "repo-L", "party": "party-L"}, {"slug": "repo-W", "party": "party-W"}],
    "application": [{"slug": "app-L", "repo": "repo-L"}],
    # one row, two cells at the loser: both must move in one write
    "invoice": [{"slug": "inv-1", "seller": "party-L", "buyer": "party-W", "book_owner": "party-L"}],
}


class Store:
    def __init__(self):
        self.rows = copy.deepcopy(SEED)
        self.writes, self.audits = [], []
        self.cols = {}
        for p in TABLES.glob("*.table.yml"):
            tdef = ND._load_def(TABLES, p.name[: -len(".table.yml")]) or {}
            for c in ND._rowref_cols(tdef):
                self.cols.setdefault(p.name[: -len(".table.yml")], []).append((c["key"], c.get("refTable")))

    def read(self, table):
        return copy.deepcopy(self.rows.get(table, []))

    def write_row(self, table, row):
        self.writes.append((table, row["slug"]))
        self.rows[table] = [row if r["slug"] == row["slug"] else r for r in self.rows[table]]

    def referrers(self, table, slug):
        return [{"fromTable": t, "fromRow": r["slug"], "columnKey": k}
                for t, cols in self.cols.items() for k, ref in cols if ref == table
                for r in self.rows.get(t, []) if r.get(k) == slug]

    def delete_row(self, table, slug):
        if self.referrers(table, slug):
            raise RuntimeError(f"restrict: {table}/{slug} still referenced")
        self.writes.append((table, f"-{slug}"))
        self.rows[table] = [r for r in self.rows[table] if r["slug"] != slug]

    def merge(self, confirm=True):
        return ND.merge_party("party-L", "party-W", self.read, TABLES, write_row=self.write_row,
                              delete_row=self.delete_row, referrers=self.referrers,
                              audit=self.audits.append, confirm=confirm)


def test_restrict_refuses_deleting_the_loser_while_referenced():
    with pytest.raises(RuntimeError):
        Store().delete_row("party", "party-L")


def test_plan_lists_every_cell_pointing_at_the_loser():
    plan = ND.merge_plan("party-L", "party-W", Store().read, TABLES)
    cells = {(c["table"], c["slug"], c["column"]) for c in plan["cells"]}
    assert cells == {("party-tax-identity", "tax-L", "party"), ("party-contact", "mail-L", "party"),
                     ("repo", "repo-L", "party"), ("invoice", "inv-1", "seller"),
                     ("invoice", "inv-1", "book_owner")}


def test_dry_run_writes_nothing():
    s = Store()
    out = s.merge(confirm=False)
    assert out["dry"] and len(out["cells"]) == 5
    assert s.writes == [] and s.audits == [] and s.rows == SEED


def test_merge_repoints_deletes_audits_and_leaves_the_winner_alone():
    s = Store()
    out = s.merge()
    assert out["deleted"] and out["refused"] is None
    assert "party-L" not in {r["slug"] for r in s.rows["party"]}
    assert s.referrers("party", "party-L") == []
    inv = s.rows["invoice"][0]
    assert inv["seller"] == inv["book_owner"] == inv["buyer"] == "party-W"
    assert s.rows["application"] == SEED["application"]          # a grandchild is not a cell
    touched = {slug for _, slug in s.writes}
    assert not touched & {"tax-W", "repo-W", "party-W"}          # the winner's rows untouched
    assert s.writes.count(("invoice", "inv-1")) == 1             # two cells, one write
    assert len(s.audits) == 1 and s.audits[0]["loser"] == "party-L"


def test_rerun_is_a_noop():
    s = Store()
    s.merge()
    writes, audits = list(s.writes), list(s.audits)
    out = s.merge()
    assert out["cells"] == [] and not out["deleted"]
    assert s.writes == writes and s.audits == audits


def test_a_referrer_outside_the_walk_blocks_the_delete():
    s = Store()
    s.cols.setdefault("ghost", []).append(("party", "party"))   # a table with no def in this repo
    s.rows["ghost"] = [{"slug": "g1", "party": "party-L"}]
    out = s.merge()
    assert not out["deleted"] and "1 referrer" in out["refused"]
    assert "party-L" in {r["slug"] for r in s.rows["party"]}
    assert s.audits and s.audits[0]["refused"]


def test_self_merge_and_unknown_winner_are_refused():
    s = Store()
    with pytest.raises(ValueError):
        ND.merge_plan("party-L", "party-L", s.read, TABLES)
    with pytest.raises(ValueError):
        ND.merge_plan("party-L", "party-nope", s.read, TABLES)


def test_a_failed_delete_still_audits_the_repointed_rows():
    s = Store()

    def deny(table, slug):
        raise OSError("403 human door")
    s.delete_row = deny
    with pytest.raises(OSError):
        s.merge()
    assert s.rows["invoice"][0]["seller"] == "party-W"           # writes landed before the failure
    assert len(s.audits) == 1 and s.audits[0]["repointed"] and not s.audits[0]["deleted"]
    assert "403" in s.audits[0]["refused"]


def test_an_ico_slug_never_loses_to_a_name_slug():
    s = Store()
    s.rows["party"].append({"slug": "party-ico-00000112"})
    with pytest.raises(ValueError, match="importer"):
        ND.merge_plan("party-ico-00000112", "party-W", s.read, TABLES)
    ND.merge_plan("party-W", "party-ico-00000112", s.read, TABLES)   # the other way is fine
