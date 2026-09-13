"""ssot/INDEX.yml is the realm map. A folder under ssot/ that is not that map is a copy.

doctrine lives here. genome, dtt, idea, fee keep the paths the INDEX names.
ssot/genome, ssot/dtt, ssot/idea, ssot/fee must not exist — those realms are
not owned as trees in this public repo (dtt is private; genome already has a
home; idea and fee are not in force).
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
INDEX = REPO / "ssot" / "INDEX.yml"


def _index() -> dict:
    data = yaml.safe_load(INDEX.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and "realms" in data
    return data


def test_index_exists_and_names_five_realms():
    data = _index()
    assert data.get("prefix") == "nos-sot"
    assert set(data["realms"]) == {"doctrine", "genome", "idea", "dtt", "fee"}


def test_each_in_repo_realm_path_exists():
    data = _index()
    missing = []
    for name, spec in data["realms"].items():
        path = spec["path"]
        if path.startswith("$"):
            continue
        if not (REPO / path).exists():
            missing.append(f"{name}: {path}")
    assert not missing, missing


def test_doctrine_is_the_only_ssot_tree():
    data = _index()
    assert data["realms"]["doctrine"]["path"] == "ssot/doctrine"
    assert data["realms"]["genome"]["path"] == "state/genome"
    assert data["realms"]["dtt"]["path"] == "$NOS_SEED_DIR"
    assert data["realms"]["dtt"].get("public") is False
    copies = [
        p.name for p in (REPO / "ssot").iterdir()
        if p.is_dir() and p.name in {"genome", "idea", "dtt", "fee"}
    ]
    assert copies == [], f"ssot/ has copied realms {copies}; INDEX path is the location"


def test_dtt_is_not_in_this_repo():
    assert not (REPO / "ssot" / "dtt").exists()
    assert not (REPO / "ssot" / "genome").exists()


def _cite():
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(
        "doctrine_cite", REPO / "tools" / "doctrine-cite.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["doctrine_cite"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_ssot_stub_keeps_docs_path_as_an_address():
    corpus = _cite().build_corpus()
    stub = corpus["docs/doctrine/ssot.md"]
    live = corpus["ssot/doctrine/ssot.md"]
    assert live.sections, "ssot/doctrine/ssot.md has no numbered sections"
    assert stub.sections == live.sections


def test_every_moved_stub_aliases_the_live_article():
    """A stub that no longer copies numbered headings is a broken § address."""
    corpus = _cite().build_corpus()
    drifted = []
    for stub_path in sorted((REPO / "docs" / "doctrine").glob("*.md")):
        text = stub_path.read_text(encoding="utf-8")
        if "Moved to" not in text:
            continue
        rel = stub_path.relative_to(REPO).as_posix()
        live_rel = f"ssot/doctrine/{stub_path.name}"
        if live_rel not in corpus:
            drifted.append(f"{rel} has no {live_rel}")
            continue
        if corpus[rel].sections != corpus[live_rel].sections:
            drifted.append(f"{rel} sections != {live_rel}")
    assert not drifted, drifted
