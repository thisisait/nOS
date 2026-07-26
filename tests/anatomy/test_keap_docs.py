"""KEAP docs-as-knowledge generator — contract gate (offline, fast).

Pins `files/anatomy/scripts/keap_docs_gen.py`, the companion that walks
`docs/systems/` prose into typed KEAP nodes (`docs/plans/cortex-docs-schema.md`).
It asserts the six decisions where they are checkable in the producer:

  §1/§2  the four kinds are DECLARED from block signals, not inferred from topic
  §3     doc nodes anchor on the system node they are about (merged, not mirrored)
  §4     provenance rides the sidecar, never the embedded body
  §5     every id routes through the one slug gate (no second charset)
  §6     coverage is DATA — services MISSED are named, not silently absent

The last is the one the C1 self-model gap was missing: coverage that is logged
and never asserted is indistinguishable from full coverage. Here it is asserted.
"""
import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
GEN = ROOT / "files/anatomy/scripts/keap_docs_gen.py"
SELFMODEL_GEN = ROOT / "files/anatomy/scripts/keap_selfmodel_gen.py"
MANIFEST = ROOT / "state/manifest.yml"
DOCS_ROOT = ROOT / "docs/systems"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gen():
    return _load(GEN, "keap_docs_gen")


def _build():
    return _gen().build_docs(str(MANIFEST), str(DOCS_ROOT), str(ROOT))


# ── sources ───────────────────────────────────────────────────────────────────

def test_generator_and_sources_exist():
    assert GEN.is_file(), "docs generator missing"
    assert SELFMODEL_GEN.is_file() and MANIFEST.is_file() and DOCS_ROOT.is_dir()


def test_it_reuses_the_one_slug_gate_no_second_charset():
    """§5: the docs gen slugs through keap_selfmodel_gen — not a private copy."""
    mod = _gen()
    assert mod.sm.slug_or_die is not None
    # a leading-digit segment dies loudly through the SAME gate the self-model uses
    with pytest.raises(SystemExit):
        mod.sm.slug_or_die("2fa", "doc block")


# ── §1/§2: kinds are declared from block signals ────────────────────────────────

@pytest.mark.parametrize("lines,default,expect", [
    (['**Trigger:** "make a repo"', "**Endpoint:** `POST /x`"], "note", "skill"),
    (["**When** the volume is unmounted:", "wait for the remount"], "note", "hint"),
    (["**If** GitLab cold-inits, wait"], "note", "hint"),
    (["```bash", "echo hi", "```"], "note", "snippet"),
    (["Just a standing claim about the estate."], "note", "note"),
    (["Body under a file that declared itself."], "skill", "skill"),
])
def test_classify_reads_the_declared_signal(lines, default, expect):
    assert _gen().classify(lines, default)["kind"] == expect


def test_trigger_beats_a_code_block_skill_not_snippet():
    """§1 skill-vs-snippet wall: a skill carrying a ```block is still a skill."""
    lines = ['**Trigger:** "do it"', "```json", "{}", "```"]
    assert _gen().classify(lines, "note")["kind"] == "skill"


def test_frontmatter_type_default_is_note():
    mod = _gen()
    assert mod.parse_frontmatter("plain body, no fence")[0] is None
    assert mod.parse_frontmatter("---\ntype: skill\ntitle: x\n---\nbody")[0] == "skill"
    # an unknown type is ignored — the safe default note wins, not a bogus kind
    assert mod.parse_frontmatter("---\ntype: bogus\n---\nbody")[0] is None


def test_sections_are_fence_aware():
    """A '#'-led line inside a code fence is content, never a heading split."""
    body = "## Real\ntext\n```\n# not a heading\n```\nmore"
    titles = [t for t, _ in _gen().iter_sections(body)]
    assert titles == ["Real"]


# ── §4: provenance in the sidecar, never the body ──────────────────────────────

def test_provenance_shape_and_git_blob_sha():
    mod = _gen()
    # b"hello" is NOT the committed bytes of gitea/README.md, so this is a DIRTY
    # provenance: the five core keys are always present; the blob is the working
    # bytes, and because they are not in the last commit the pair is not paired —
    # commit drops to null and `dirty` flags WHY (not "no git", but "uncommitted").
    data = b"hello"
    prov = mod.provenance(str(ROOT), str(DOCS_ROOT / "gitea/README.md"), data)
    assert {"repo", "path", "commit", "blob_sha", "generated_at"} <= set(prov)
    assert prov["path"] == "docs/systems/gitea/README.md"
    # git-blob sha == `git hash-object` of the same bytes (verified: sha1 of the
    # framed blob), computed without git so it is stable for a dirty/untracked file
    assert prov["blob_sha"] == mod.git_blob_sha(data)
    assert prov["dirty"] is True and prov["commit"] is None


def test_provenance_is_in_brief_not_in_the_embedded_en():
    """§4: the churning commit/blob live in brief (→ taxonomy_metadata); the en
    (→ node_descriptions, the only embedded text) must never carry them, or every
    commit re-embeds the corpus (hidden_fees/04)."""
    docs = _build()
    checked = 0
    for nodes in docs["nodes_by_domain"].values():
        for n in nodes:
            assert "provenance" in n["brief"] and n["brief"]["provenance"]["path"]
            commit = n["brief"]["provenance"]["commit"]
            if commit:
                assert commit not in n["en"], f"{n['id']} leaked its commit into the body"
                checked += 1
    assert checked > 0, "no committed provenance to check — wrong repo state?"


def _tiny_repo(tmp_path, rel, content: str):
    import os
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / os.path.dirname(rel)).mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(content)

    def g(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    g("add", "-A")
    g("commit", "-q", "-m", "init")
    return repo


def test_provenance_commit_and_blob_never_describe_different_bytes(tmp_path):
    """§4: 'commit+blob together make staleness a query' is only true if the two
    describe the SAME bytes. `commit` came from committed HEAD history while
    `blob_sha` came from the WORKING-TREE bytes — for a dirty file (the common
    case while authoring / running against a copy) the pair is self-contradictory:
    the named commit's version of the path hashes to something else, so
    `git cat-file blob <blob_sha>` is unreachable from `commit`. The invariant:
    if `commit` is present, `blob_sha` MUST resolve from it."""
    import os as _os
    mod = _gen()
    rel = "docs/systems/gitea/README.md"
    repo = _tiny_repo(tmp_path, rel, "committed content\n")
    abs_path = str(repo / rel)

    # clean: commit present AND the blob it names resolves to blob_sha
    clean = open(abs_path, "rb").read()
    prov = mod.provenance(str(repo), abs_path, clean)
    assert prov["commit"] is not None
    assert mod.git_blob_at(str(repo), prov["commit"], prov["path"]) == prov["blob_sha"]

    # dirty: the bytes we embed differ from what any commit records
    dirty = b"uncommitted edit that no commit holds\n"
    prov2 = mod.provenance(str(repo), abs_path, dirty)
    assert prov2["blob_sha"] == mod.git_blob_sha(dirty)
    if prov2["commit"] is not None:
        assert mod.git_blob_at(str(repo), prov2["commit"], prov2["path"]) == prov2["blob_sha"], \
            "commit names bytes that are NOT blob_sha — the self-contradiction"


def test_coverage_counts_unresolved_provenance(tmp_path):
    """The compounding half: outside a git repo (or dirty) `commit` is silently
    null. That absence must be COUNTED, not swallowed — a corpus where every
    doc node's provenance is unresolvable should say so."""
    # a docs tree that is NOT under any git repo → every commit resolves to null
    cov = _one_service_docs(tmp_path, {"README.md": "## Setup\nbody\n"})["coverage"]
    assert "provenance_unresolved" in cov
    assert cov["provenance_unresolved"] == cov["doc_nodes"] > 0


# ── §6: coverage is DATA, services missed are NAMED ────────────────────────────

def test_coverage_is_data_and_partitions_the_estate():
    cov = _build()["coverage"]
    # every kind counted, and the counts sum to the node total (nothing lost)
    assert set(cov["nodes_by_kind"]) == {"skill", "hint", "note", "snippet"}
    assert sum(cov["nodes_by_kind"].values()) == cov["doc_nodes"] > 0
    # covered ⊎ missed == the whole estate: a service is documented or it is
    # MISSED, never silently absent (the fee this schema is paying down)
    covered, missed = set(cov["services_covered"]), set(cov["services_missed"])
    assert covered.isdisjoint(missed)
    assert len(covered) + len(missed) == cov["services_total"]


def test_the_gap_is_reported_by_name_not_hidden(tmp_path):
    """The deliverable's hard rule: a service without a docs tree appears as
    MISSED by name, so silence can never be read as 'no such capability'.

    Pinned against a CONTROLLED gap — a docs-root holding only gitea's tree —
    rather than the live estate, because the live estate is now FULLY documented
    (feat/cortex-docs-knowledge authored all 63 trees): asserting a specific live
    service is undocumented would encode a gap the branch deliberately closed.
    The mechanism under test is independent of how much happens to be covered."""
    cov = _one_service_docs(tmp_path, {"README.md": "## Setup\nbody\n"})["coverage"]
    assert "gitea" in cov["services_covered"]
    for undocumented in ("traefik", "gitlab", "postgresql"):
        assert undocumented in cov["services_missed"], f"{undocumented} silently absent"
    # with only one tree present, the gap is the overwhelming majority — surfaced
    # as named data, never as a silent absence
    assert len(cov["services_missed"]) > len(cov["services_covered"])


def test_live_estate_is_fully_documented(tmp_path):
    """The branch's deliverable, pinned as a fact: every manifest service has a
    docs tree that produces at least one node, so the live coverage report shows
    zero missed and zero empty. If a future service lands in the manifest without
    a docs/systems/<svc>/ tree, THIS is the gate that turns red and names it."""
    cov = _build()["coverage"]
    assert cov["services_missed"] == [], f"undocumented services: {cov['services_missed']}"
    assert cov["services_empty"] == [], f"empty doc trees: {cov['services_empty']}"
    assert len(cov["services_covered"]) == cov["services_total"]


def test_every_kind_is_producible_even_where_the_corpus_has_none():
    """Every kind is producible; the live counts are whatever the corpus DECLARES,
    which is the honest result of a declared-not-inferred contract. hints are rare
    (3 today, all in pulse/README.md, each a genuinely conditional heading) because
    a hint requires a leading `**When`/`**If` — so this proves the classifier still
    produces one when the signal IS present, rather than pinning a count that moves
    whenever a card is written.

    NB the signal is section-wide: ONE `**When`-leading line retypes its whole
    section, which is how home-assistant's Authentication section briefly became a
    hint and lost its standing credential facts to a `note` filter (S1)."""
    cov = _build()["coverage"]
    assert cov["nodes_by_kind"]["skill"] > 0 and cov["nodes_by_kind"]["note"] > 0
    assert _gen().classify(["**When** X happens: do Y"], "note")["kind"] == "hint"


# ── merge + determinism + loud failure ─────────────────────────────────────────

def _selfmodel_tree(tmp_path):
    sm = _load(SELFMODEL_GEN, "keap_selfmodel_gen")
    model = sm.build_slug_model(str(MANIFEST), str(DOCS_ROOT))
    files = sm.render_canonical(model)
    res = {"created": 0, "updated": 0, "unchanged": 0, "removed": 0}
    import os
    for rel, body in files.items():
        sm._write_if_changed(str(tmp_path / "canonical" / rel), body, res)
    return tmp_path / "canonical"


def test_merge_lands_doc_nodes_under_their_system_and_is_deterministic(tmp_path):
    mod = _gen()
    docs = _build()
    a = _selfmodel_tree(tmp_path / "a")
    b = _selfmodel_tree(tmp_path / "b")
    mod.generate(str(a), docs)
    mod.generate(str(b), docs)
    devops_a = json.loads((a / "nos" / "nos.devops.json").read_text())
    ids = {n["id"] for n in devops_a["nodes"]}
    assert "nos.devops.gitea" in ids                       # the system stayed
    assert "nos.devops.gitea.skills-create-repo" in ids    # a doc child landed under it
    # two fresh merges are byte-identical (determinism the fs-sync skip relies on)
    assert (a / "nos" / "nos.devops.json").read_text() == (b / "nos" / "nos.devops.json").read_text()


def _one_service_docs(tmp_path, files: dict[str, str]):
    """A docs-root holding exactly one manifest service's tree (gitea, devops),
    so build_docs runs the real manifest but walks only the prose under test.
    Returns the coverage-carrying build result."""
    docs = tmp_path / "systems"
    (docs / "gitea").mkdir(parents=True)
    for name, body in files.items():
        (docs / "gitea" / name).write_text(body)
    return _gen().build_docs(str(MANIFEST), str(docs), str(ROOT))


def _gitea_doc_nodes(res):
    return [n for nodes in res["nodes_by_domain"].values()
            for n in nodes if n["id"].startswith("nos.devops.gitea.")]


def test_repeated_heading_text_coexists_not_crashes(tmp_path):
    """A second section that shares heading TEXT with an earlier one — a second
    `## Notes`, `### Example`, `### Parameters`, all routine when one file
    documents several skills/endpoints — must NOT raise `duplicate doc block id`
    and abort keap_docs_gen, which fails the WHOLE organ boot (runDocs throws).
    The schema invites strangers to write ordinary markdown; two identical
    sub-headings is ordinary markdown. They must land as distinct nodes."""
    res = _one_service_docs(tmp_path, {
        "README.md": "## Notes\nfirst body\n\n## Notes\nsecond body\n",
    })
    ids = [n["id"] for n in _gitea_doc_nodes(res)]
    assert len(ids) == 2, ids
    assert len(set(ids)) == 2, f"repeated heading collapsed to one id: {ids}"


def test_ordinal_orders_children_across_source_files(tmp_path):
    """`ordinal` is the field that SEQUENCES a system's doc children. With the
    per-file index reset, README section N, AGENTS section N and SKILLS section N
    all collided on 100+N, so sorting a system's children strictly by ordinal —
    the field's stated purpose — produced ties it could not break. Make it
    monotonic across the whole system so README-then-AGENTS-then-SKILLS ordering
    is actually expressed by the data."""
    res = _one_service_docs(tmp_path, {
        "README.md": "## A\nalpha\n\n## B\nbeta\n",
        "AGENTS.md": "## C\ngamma\n\n## D\ndelta\n",
    })
    ords = sorted(n["ordinal"] for n in _gitea_doc_nodes(res))
    assert len(ords) == 4, ords
    assert len(set(ords)) == 4, f"ordinals are not unique across files: {ords}"
    assert ords == list(range(ords[0], ords[0] + 4)), f"ordinals are not monotonic: {ords}"


def test_unrecognized_doc_files_are_revealed_by_name(tmp_path):
    """A service whose prose lives in RUNBOOK.md / GUIDE.md — or a typo'd
    AGENT.md — falls outside the fixed README/AGENTS/SKILLS allowlist and
    contributes zero nodes with no signal. Authored prose that exists on disk
    must be REVEALED as a counter (`docs_ignored`), never silently omitted."""
    cov = _one_service_docs(tmp_path, {
        "README.md": "## Setup\nreadme body\n",
        "RUNBOOK.md": "## Ops\nrunbook prose that would otherwise be lost\n",
    })["coverage"]
    assert "gitea" in cov["services_covered"]          # README parsed → covered
    assert "docs_ignored" in cov, "no counter reveals the dropped file"
    assert any(x.endswith("gitea/RUNBOOK.md") for x in cov["docs_ignored"])


def test_tree_present_but_ignored_is_not_conflated_with_no_tree(tmp_path):
    """`services_missed` is field-documented as 'no docs/systems/<svc>/ tree', but
    a service WITH a tree that produced zero parseable nodes was routed there too
    — 'no docs tree' and 'docs present but ignored' collapsed to one value. The
    tree's existence must be distinguishable."""
    cov = _one_service_docs(tmp_path, {
        "RUNBOOK.md": "## Ops\nonly ignored prose, no README/AGENTS/SKILLS\n",
    })["coverage"]
    assert "gitea" in cov["services_missed"]            # still: no USABLE docs
    assert "gitea" in cov.get("services_empty", [])     # but the tree EXISTS
    assert any(x.endswith("gitea/RUNBOOK.md") for x in cov["docs_ignored"])
    # a service with no tree at all is missed but NOT empty — the two are distinct
    assert "traefik" in cov["services_missed"]
    assert "traefik" not in cov.get("services_empty", [])


def test_zero_doc_nodes_fails_loudly(tmp_path):
    """Absence is not emptiness: a docs-root with nothing to walk must exit
    non-zero so the store refuses to boot, not log and continue."""
    empty = tmp_path / "empty-docs"
    empty.mkdir()
    canonical = _selfmodel_tree(tmp_path / "sm")
    rc = _gen().main([
        "--manifest", str(MANIFEST),
        "--docs-root", str(empty),
        "--canonical", str(canonical),
        "--repo-root", str(ROOT),
    ])
    assert rc == 3, "zero doc nodes must be a loud non-zero exit"
