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


def test_retained_by_survivors_keeps_what_a_surviving_firm_needs():
    """teardown-fork-free's retention half (its named judge). A row whose only
    referrer is also being removed is safe to delete; a referrer NOT in the
    planned set (another firm) retains it."""
    refs = [{"fromTable": "repo", "fromRow": "repo-A"}, {"fromTable": "repo", "fromRow": "repo-B"}]
    assert ND.retained_by_survivors(refs, {("repo", "repo-A")}) == \
        [{"fromTable": "repo", "fromRow": "repo-B"}]                 # B survives → retain
    assert ND.retained_by_survivors(refs, {("repo", "repo-A"), ("repo", "repo-B")}) == []  # all removed → delete


def test_rows_from_envelope_reads_both_shapes():
    """The false-'wrote' fix, pinned: the parse must read rows nested under `data`
    (the real KEAP envelope) AND the flat shape, and not crash on empty."""
    import importlib.util
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    spec = importlib.util.spec_from_file_location("digest_absorb", REPO / "tools" / "digest_absorb.py")
    da = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(da)
    rows = [{"slug": "x"}]
    assert da._rows_from_envelope({"success": True, "data": {"rows": rows}}) == rows  # nested (real)
    assert da._rows_from_envelope({"rows": rows}) == rows                             # flat
    assert da._rows_from_envelope({}) == []


def test_party_graph_centres_on_the_party_and_wires_the_closure():
    g = ND.party_graph("party-A", _reader, TABLES)
    ids = {n["id"] for n in g["nodes"]}
    assert "party:party-A" in ids                              # the kmenová-data centre
    assert {"repo:repo-A", "application:app-A", "package:pkg-A"} <= ids
    assert not any(n["slug"].endswith("-B") for n in g["nodes"])   # one party's subgraph only
    # facet + derived rows wire IN to the party; the chain wires child -> parent
    assert any(e["to"] == "party:party-A" and e["column"] == "party" for e in g["edges"])
    assert any(e["from"] == "application:app-A" and e["to"] == "repo:repo-A" for e in g["edges"])
    assert any(e["from"] == "package:pkg-A" and e["to"] == "application:app-A" for e in g["edges"])
