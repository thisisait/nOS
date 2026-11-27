"""The SECOND importer — repos → software-estate chain — offline half.

Proves the harness generalises off CSV (a directory of repos, three ecosystems,
a 4-table rowRef chain) and that party-resolver dedups: two repos owned by the
same IČO reuse ONE party row, an unknown owner is refused (never minted). The
party index is injected here; the live index (from KEAP) is the CLI's job.
The fixture manifests are committed as `*.fixture`; stage_fixture() copies them
under their real names before the importer walks the tree.
"""
import importlib.util
import pathlib

import pytest

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


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    _nd, mod = _load()
    root = tmp_path_factory.mktemp("staged")
    return lambda name: mod.stage_fixture(FIXTURE.with_name(name), root / name)


@pytest.fixture(scope="module")
def repos_bundle(staged):
    nd, mod = _load()
    imp = mod.RepoImporter("repos-fixture", INDEX, fixture_mode=True)
    bundle, errors = nd.run_importer(imp, str(staged("repos-fixture")), TABLES)
    return nd, imp, bundle, errors


def test_gate_passes_the_full_rowref_chain(repos_bundle):
    _nd, _imp, bundle, errors = repos_bundle
    assert errors == [], errors
    keys = list(bundle["deterministic"].keys())
    assert keys[0] == "party"
    assert keys[-3:] == ["repo", "application", "package"]


def test_two_repos_same_owner_dedup_to_one_party(repos_bundle):
    _nd, imp, bundle, _ = repos_bundle
    parties = bundle["deterministic"]["party"]
    hits = [p for p in parties if p.get("__visibility") != "system"]
    assert [p["slug"] for p in hits] == ["synthetic-mesto-lipno"]   # ONE, not two
    review = [p for p in parties if p.get("__visibility") == "system"]
    assert review and all("review-batch:" in (p.get("notes") or "") for p in review)
    repos = {r["slug"] for r in bundle["deterministic"]["repo"]}
    assert len(repos) == 2                                             # portal + api
    assert all(r["party"] == "synthetic-mesto-lipno" for r in bundle["deterministic"]["repo"])
    assert any("orphan-tool" in s and "review" in s for s in imp.skipped), imp.skipped


def test_multi_ecosystem_packages_and_monorepo_apps(repos_bundle):
    _nd, _imp, bundle, _ = repos_bundle
    apps = bundle["deterministic"]["application"]
    assert len(apps) == 3          # portal(1) + api root(1) + api/worker(1)
    ecos = {p["ecosystem"] for p in bundle["deterministic"]["package"]}
    assert ecos == {"npm", "pypi", "go"}
    assert len(bundle["deterministic"]["package"]) == 8   # 3 npm + 3 pypi + 2 go


def test_every_row_carries_provenance_and_teardown_is_leaf_first(repos_bundle):
    nd, _imp, bundle, _ = repos_bundle
    for rows in bundle["deterministic"].values():
        for r in rows:
            assert nd.PROV_REQUIRED <= set(r["_prov"]), r
    plan = nd.teardown_plan(bundle)
    order = [t for t, _ in plan]
    # package deleted before application before repo before party (leaf-first)
    assert order.index("package") < order.index("application") < order.index("repo") < order.index("party")


def test_composer_cargo_and_csproj_yield_package_rows(staged):
    nd, mod = _load()
    imp = mod.RepoImporter("repos-fixture-ecosystems", INDEX, fixture_mode=True)
    bundle, errors = nd.run_importer(imp, str(staged("repos-fixture-ecosystems")), TABLES)
    assert errors == [], errors
    got = {(p["ecosystem"], p["name"], p["version"]) for p in bundle["deterministic"]["package"]}
    # composer platform reqs (php, ext-*) are not packages; a path dep has no version
    assert got == {("composer", "nette/application", "^3.2"), ("composer", "phpunit/phpunit", "^11.0"),
                   ("cargo", "anyhow", "1.0"), ("cargo", "serde", "1.0.200"),
                   ("cargo", "local-util", ""), ("cargo", "tempfile", "3"),
                   ("nuget", "Newtonsoft.Json", "13.0.3"), ("nuget", "Serilog", "4.0.0")}
