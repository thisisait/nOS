"""GDPR erasure closure for the digest organ (gdpr-digestion-stage / erasure-party-subject).

nos_digest.erasure_plan enumerates every row importers wrote that hangs off a
party — the rowRef-DOWN closure — so a data-subject erasure reaches the derived
data, not just the party record. The edge set is READ from the real table defs
(state/keap-tables), the rows from an injected reader, so this runs offline. The
party row itself is never in the closure; one party's subtree never pulls another's.
"""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
TABLES = REPO / "state" / "keap-tables"


def _nd():
    spec = importlib.util.spec_from_file_location(
        "nos_digest", REPO / "files" / "anatomy" / "module_utils" / "nos_digest.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ND = _nd()

# Two parties, each with a tax-identity facet + a repo → application → package
# chain. A package name shared by both firms is still two DISTINCT rows (slug is
# per application), so there is no shared derived row to fight over.
ROWS = {
    "party": [{"slug": "party-A"}, {"slug": "party-B"}],
    "party-tax-identity": [{"slug": "tax-A", "party": "party-A", "scheme": "ICO", "value": "1"},
                           {"slug": "tax-B", "party": "party-B", "scheme": "ICO", "value": "2"}],
    "repo": [{"slug": "repo-A", "party": "party-A"}, {"slug": "repo-B", "party": "party-B"}],
    "application": [{"slug": "app-A", "repo": "repo-A"}, {"slug": "app-B", "repo": "repo-B"}],
    "package": [{"slug": "pkg-A", "application": "app-A"}, {"slug": "pkg-B", "application": "app-B"}],
}


def _reader(table):
    return ROWS.get(table, [])


def test_closure_reaches_the_derived_rows_and_the_facets():
    plan = ND.erasure_plan("party-A", _reader, TABLES)
    assert plan["repo"][0]["slug"] == "repo-A"
    assert plan["application"][0]["slug"] == "app-A"
    assert plan["package"][0]["slug"] == "pkg-A"
    assert plan["party-tax-identity"][0]["slug"] == "tax-A"   # a facet, transitively erased


def test_the_party_row_itself_is_never_in_the_closure():
    plan = ND.erasure_plan("party-A", _reader, TABLES)
    assert "party" not in plan          # the root is retained (person-vs-org is deferred)


def test_one_partys_subtree_never_pulls_anothers():
    plan = ND.erasure_plan("party-A", _reader, TABLES)
    all_slugs = {s for rows in plan.values() for r in rows for s in [r["slug"]]}
    assert not any(s.endswith("-B") for s in all_slugs), all_slugs


def test_teardown_of_the_closure_is_leaf_first():
    plan = ND.erasure_plan("party-A", _reader, TABLES)
    order = [t for t, _ in ND.teardown_plan(plan)]
    assert order.index("package") < order.index("application") < order.index("repo")
