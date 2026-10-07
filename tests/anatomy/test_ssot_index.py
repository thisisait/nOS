"""ssot/INDEX.yml is the realm map. A folder under ssot/ that is not that map is a copy.

doctrine lives here. genome, dtt, idea, fee, systems keep the paths the INDEX names.
ssot/genome, ssot/dtt, ssot/idea, ssot/fee, ssot/systems must not exist — those
realms are not owned as trees in this public repo.

Address form: nos-sot:doctrine/ssot.md#1
"""
from __future__ import annotations

import re
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


def test_an_old_doctrine_path_is_still_an_address():
    """History cites the warehouse path of ssot.md; the redirect keeps it an address."""
    corpus = _cite().build_corpus()
    old = corpus["docs/doctrine/ssot.md"]
    live = corpus["ssot/doctrine/ssot.md"]
    assert live.sections, "ssot/doctrine/ssot.md has no numbered sections"
    assert old.sections == live.sections
    assert corpus["docs/doctrine/organs.md"].sections == \
        corpus["ssot/doctrine/body-plan.md"].sections


#: Articles written in ssot/ from part of a guide that stays a guide: no
#: warehouse file was moved, so there is no old address to redirect.
_BORN_IN_SSOT = {
    "sso.md": "carved from docs/sso-and-attribution.md, which stays the guide",
    "genome.md": "the shipped half of docs/idea/06-genome.md, which stays an idea",
}


def test_every_promoted_article_keeps_its_old_address():
    """Each article has a redirect from its warehouse path, the redirect's
    target is live, and no stub file sits beside it (law has one home)."""
    cite = _cite()
    corpus = cite.build_corpus()
    redirects = cite.DOCTRINE_REDIRECTS
    bad = [f"{old} -> {new} (target missing)" for old, new in redirects.items()
           if not (REPO / new).is_file()]
    bad += [f"{old} still on disk" for old in redirects if (REPO / old).exists()]
    bad += [f"{old} sections != {new}" for old, new in redirects.items()
            if new in corpus and corpus[old].sections != corpus[new].sections]
    targets = set(redirects.values())
    bad += [f"ssot/doctrine/{p.name} has no old address"
            for p in sorted((REPO / "ssot" / "doctrine").glob("*.md"))
            if f"ssot/doctrine/{p.name}" not in targets and p.name not in _BORN_IN_SSOT]
    assert not bad, bad


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
        "docs/doctrine/backoffice.md",
        "docs/doctrine/n8n-packs.md",
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


#: Trees doctrine-cite deliberately skips (SKIP_FILES_PREFIX / vendored ports)
#: are blind to the harvest gate above — that is how visibility.ts's stub-path
#: cite to the identity article survived promotion. Files that name a stub
#: path as DATA, not as a live cite, are allowed:
#:   - the stub-alias gate + proposed list (this file)
#:   - frozen published devlog history (content_hash-pinned)
#:   - the frozen cross-repo negotiation record
#:   - finished workflows whose task text records the old tree (RECORD)
_STUB_PATH_ALLOW = {
    "tests/anatomy/test_ssot_index.py",
    "tools/doctrine-cite.py",  # DOCTRINE_REDIRECTS: the old paths, as data
    ".claude/workflows/ssot-promote.js",
    ".claude/workflows/wave-small-ssot.js",
    "state/devlog-bundle.jsonl",
    "files/anatomy/cortex/docs/specs/nos-selfmodel-keap-contract.md",
}


def test_code_does_not_cite_promoted_stub_paths():
    """Every code cite to a promoted article names ssot/doctrine/<file>.md or
    nos-sot:doctrine/<file>#id — never the warehouse stub, which would keep the
    stub load-bearing forever (nos-sot:doctrine/ssot.md#3). Covers the trees the
    harvester skips; retro-red on the old `docs/doctrine/<file>.md` form.
    Also covers the briefs and config layers a model reads first, and a
    `docs/doctrine/<file>.md` that no longer exists (a dangling path)."""
    import re
    import sys
    promoted = {p.stem for p in (REPO / "ssot" / "doctrine").glob("*.md")}
    pat = re.compile(r"docs/doctrine/([A-Za-z0-9-]+)\.md")
    suffixes = {".py", ".yml", ".yaml", ".sh", ".php", ".ts", ".svelte", ".j2",
                ".md", ".cfg", ".neon", ".sql", ".js", ".latte", ".json"}
    skip_dirs = {"node_modules", ".svelte-kit", "build", "dist", "vendor"}
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity  # noqa: PLC0415 — the default layers, never a filename
    layers = [p.relative_to(REPO).as_posix() for p in nos_identity.default_layers()]
    offenders = []
    for root in ("files", "tools", "tasks", "roles", "state", "tests",
                 "callback_plugins", "main.yml", "CLAUDE.md", "README.md",
                 ".claude/workflows", *layers):
        base = REPO / root
        files = [base] if base.is_file() else base.rglob("*")
        for f in files:
            if not f.is_file() or f.suffix not in suffixes:
                continue
            if any(part in skip_dirs for part in f.parts):
                continue
            rel = f.relative_to(REPO).as_posix()
            if rel in _STUB_PATH_ALLOW:
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                for name in pat.findall(line):
                    if name in promoted or not (REPO / "docs/doctrine" / f"{name}.md").is_file():
                        offenders.append(f"{rel}:{i} docs/doctrine/{name}.md")
    assert not offenders, offenders


# ── force is a key (nos-sot:doctrine/ssot.md#3) ─────────────────────────────

#: Phrases that make a file read as law. Outside ssot/ only an INDEX `proposed:`
#: original may carry one in its first lines (it also says PROPOSED).
#: CEILING: exact phrases, first 6 lines only; a new paraphrase passes.
_LAW_CLAIM = re.compile(
    r"settled law|this file is the law|doctrine locked|authoritative doc"
    r"|follow it exactly|contract settled|retro doctrine|status:\W*doctrine", re.I)
#: Force banners the front matter replaced: a second, unparsed way to say it.
_FORCE_BANNER = re.compile(r"^>?\s*\**(canonical\b|status:\W*doctrine|doctrine,\s*20\d\d)", re.I | re.M)
_HISTORY = ("docs/archive/", "docs/devlog/", "docs/hidden_fees/", "RELEASE.md")
_FRONT_KEYS = ("in_force", "ruled", "row", "gates")


def _articles() -> list[Path]:
    return sorted((REPO / "ssot" / "doctrine").glob("*.md"))


def _front(path: Path) -> tuple[dict | None, str]:
    """(front matter, body). None when the file opens without `---`."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None, text
    head, _, body = text[4:].partition("\n---\n")
    return (yaml.safe_load(head) or {}), body


def test_every_article_declares_in_force():
    """Force is a key, not a banner: in_force, ruled, row, gates on every article."""
    bad = []
    for p in _articles():
        fm, _ = _front(p)
        if fm is None:
            bad.append(f"{p.name}: no front matter")
            continue
        bad += [f"{p.name}: no `{k}`" for k in _FRONT_KEYS if k not in fm]
        if not isinstance(fm.get("in_force"), bool):
            bad.append(f"{p.name}: in_force is not true|false")
    assert not bad, bad


def test_a_proposed_banner_iff_not_in_force():
    """The article's key overrides the realm flag; the banner only repeats it."""
    bad = []
    for p in _articles():
        fm, body = _front(p)
        banner = bool(re.search(r"^>\s*\*\*PROPOSED", body, re.M))
        if fm is not None and banner == bool(fm.get("in_force")):
            bad.append(f"{p.name}: in_force={fm.get('in_force')} banner={banner}")
        top = "\n".join(body.splitlines()[:8])
        if _FORCE_BANNER.search(top):
            bad.append(f"{p.name}: force banner in the first lines")
    assert not bad, bad


def test_article_gates_are_the_tests_that_cite_it():
    """`gates:` is derived (tools/doctrine-cite.py article_gates), never typed."""
    derived = _cite().article_gates()
    bad = []
    for p in _articles():
        fm, _ = _front(p)
        rel = f"ssot/doctrine/{p.name}"
        want = derived.get(rel, [])
        if fm is not None and sorted(fm.get("gates") or []) != want:
            bad.append(f"{p.name}: gates should be {want}")
    assert not bad, bad


def test_no_law_claim_outside_ssot():
    """A banner that says 'law' outside ssot/ is a second constitution."""
    import subprocess
    proposed = set(_index().get("proposed") or [])
    out = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=REPO,
                         capture_output=True, check=True).stdout.decode()
    bad = []
    for rel in sorted(r for r in out.split("\0") if r):
        if rel.startswith(("ssot/", *_HISTORY)) or rel in proposed or not (REPO / rel).is_file():
            continue
        head = (REPO / rel).read_text(encoding="utf-8", errors="replace").splitlines()[:6]
        if m := _LAW_CLAIM.search("\n".join(head)):
            bad.append(f"{rel}: {m.group(0)!r}")
    assert not bad, bad
