"""The SECOND importer — repos → software-estate chain — offline half.

Proves the harness generalises off CSV (a directory of repos, three ecosystems,
a 4-table rowRef chain) and that party-resolver dedups: two repos owned by the
same IČO reuse ONE party row, an unknown owner is refused (never minted). The
party index is injected here; the live index (from KEAP) is the CLI's job.
"""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = REPO / "state" / "fixtures" / "repos-fixture"
TABLES = REPO / "state" / "keap-tables"
# fixture party spine: Mesto Lipno holds synthetic ICO 00000112
INDEX = {"by_key": {("ICO", "00000112"): "synthetic-mesto-lipno"}, "by_name": {}}


def _load():
    import sys
    sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
    import nos_digest
    spec = importlib.util.spec_from_file_location("digest_import_repos",
                                                  REPO / "tools" / "digest-import-repos.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return nos_digest, mod


def _bundle():
    nd, mod = _load()
    imp = mod.RepoImporter("repos-fixture", INDEX, fixture_mode=True)
    bundle, errors = nd.run_importer(imp, str(FIXTURE), TABLES)
    return nd, imp, bundle, errors


def test_gate_passes_the_full_rowref_chain():
    _nd, _imp, bundle, errors = _bundle()
    assert errors == [], errors
    assert list(bundle["deterministic"].keys()) == ["party", "repo", "application", "package"]


def test_two_repos_same_owner_dedup_to_one_party():
    _nd, imp, bundle, _ = _bundle()
    parties = bundle["deterministic"]["party"]
    assert [p["slug"] for p in parties] == ["synthetic-mesto-lipno"]   # ONE, not two
    repos = {r["slug"] for r in bundle["deterministic"]["repo"]}
    assert len(repos) == 2                                             # portal + api
    assert all(r["party"] == "synthetic-mesto-lipno" for r in bundle["deterministic"]["repo"])
    assert any("orphan-tool" in s and "review" in s for s in imp.skipped), imp.skipped


def test_multi_ecosystem_packages_and_monorepo_apps():
    _nd, _imp, bundle, _ = _bundle()
    apps = bundle["deterministic"]["application"]
    assert len(apps) == 3          # portal(1) + api root(1) + api/worker(1)
    ecos = {p["ecosystem"] for p in bundle["deterministic"]["package"]}
    assert ecos == {"npm", "pypi", "go"}
    assert len(bundle["deterministic"]["package"]) == 8   # 3 npm + 3 pypi + 2 go


def test_every_row_carries_provenance_and_teardown_is_leaf_first():
    nd, _imp, bundle, _ = _bundle()
    for rows in bundle["deterministic"].values():
        for r in rows:
            assert nd.PROV_REQUIRED <= set(r["_prov"]), r
    plan = nd.teardown_plan(bundle)
    order = [t for t, _ in plan]
    # package deleted before application before repo before party (leaf-first)
    assert order.index("package") < order.index("application") < order.index("repo") < order.index("party")
