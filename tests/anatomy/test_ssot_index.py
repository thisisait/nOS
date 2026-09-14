"""ssot/INDEX.yml is the realm map. A folder under ssot/ that is not that map is a copy.

doctrine lives here. genome, dtt, idea, fee, systems keep the paths the INDEX names.
ssot/genome, ssot/dtt, ssot/idea, ssot/fee, ssot/systems must not exist — those
realms are not owned as trees in this public repo.

Address form: nos-sot:doctrine/ssot.md#1
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


def test_index_exists_and_names_the_realms():
    data = _index()
    assert data.get("prefix") == "nos-sot"
    assert set(data["realms"]) == {
        "doctrine", "genome", "systems", "idea", "dtt", "fee",
    }


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
    assert data["realms"]["systems"]["path"] == "docs/systems"
    assert data["realms"]["systems"]["in_force"] is False
    copies = [
        p.name for p in (REPO / "ssot").iterdir()
        if p.is_dir() and p.name in {"genome", "idea", "dtt", "fee", "systems"}
    ]
    assert copies == [], f"ssot/ has copied realms {copies}; INDEX path is the location"


def test_each_realm_names_who_it_is_for():
    missing = [n for n, spec in _index()["realms"].items() if not spec.get("for")]
    assert not missing, f"INDEX realm missing `for:` {missing}"


def test_dtt_is_not_in_this_repo():
    assert not (REPO / "ssot" / "dtt").exists()
    assert not (REPO / "ssot" / "genome").exists()
    assert not (REPO / "ssot" / "systems").exists()


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


def test_the_constitution_is_not_a_draft():
    """INDEX in_force on doctrine plus a PROPOSED banner on ssot.md is F1."""
    import re
    text = (REPO / "ssot" / "doctrine" / "ssot.md").read_text(encoding="utf-8")
    assert not re.search(r"^>\s*\*\*PROPOSED", text, re.M)


def test_index_names_unpromoted_proposed_files():
    data = _index()
    named = list(data.get("proposed") or [])
    assert named == [
        "docs/doctrine/agentkit.md",
        "docs/doctrine/organs.md",
    ]
    for rel in named:
        path = REPO / rel
        assert path.is_file(), rel
        text = path.read_text(encoding="utf-8")
        assert "Moved to" not in text, f"{rel} is a stub, not a proposed original"
        assert "PROPOSED" in text
        assert not (REPO / "ssot" / "doctrine" / path.name).exists(), path.name


def test_nos_sot_form_resolves_to_the_article():
    cite = _cite()
    citations, _ = cite.run()
    hits = [c for c in citations
            if c.file.endswith("test_ssot_index.py")
            and c.how == "nos-sot"
            and c.key == "1"]
    assert hits, "this file must keep a nos-sot:doctrine/ssot.md#1 cite"
    assert all(c.status == "resolved" and c.doc == "ssot/doctrine/ssot.md"
               for c in hits)


def test_harvest_cites_promoted_articles_at_ssot_path():
    """A harvest cite that still names the warehouse stub contradicts nos-sot:doctrine/ssot.md#3."""
    promoted = {p.name for p in (REPO / "ssot" / "doctrine").glob("*.md")}
    citations, _ = _cite().run()
    leftover = [
        f"{c.file}:{c.line} {c.doc} §{c.key}"
        for c in citations
        if c.doc and c.doc.startswith("docs/doctrine/")
        and c.doc.rsplit("/", 1)[-1] in promoted
    ]
    assert not leftover, leftover
