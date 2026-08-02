"""Anatomy gate: the docs corpus is an asymmetry BY DESIGN, and stays excluded.

WHY. S1 made the organ the estate's self-core: `keap_docs_gen.py` turns every
`docs/systems/<svc>/{README,AGENTS,SKILLS}.md` into typed nodes hanging off the
service node they describe. KEAP holds no such nodes and is not supposed to —
publishable reference data goes to KEAP, the estate's own material stays in nOS
(`docs/archive/cortex-self-core.md` §3).

So this population is permanently organ-only and GROWS every time anyone
documents a service. Measured on the live estate 2026-07-27: 1088 doc nodes
against 97 shared self-model nodes.

Left inside the id diff it made `clauses["taxonomy"]` false forever — and that
clause feeds `agrees`, so the three-night streak S2 exists to accumulate could
never tick once. S2 could not have anticipated it; it was designed before S1's
docs landed in the same store.

Two things are pinned here:
  1. the recogniser and `keap_docs_gen.py` agree on the id shape — if the
     generator's DOC_FILES change, this must change with them, or the diff
     silently starts counting documentation as divergence again;
  2. the exclusion is REPORTED, not silent. A withdrawn population that no
     reader can see is indistinguishable from a corpus that never had it.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "files" / "anatomy" / "scripts"
DIFF = SCRIPTS / "cortex-corpus-diff.py"
GEN = SCRIPTS / "keap_docs_gen.py"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: both modules define dataclasses, and @dataclass
    # resolves its own module by name at class-creation time — an unregistered
    # module makes that lookup return None and the import dies in dataclasses.py.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_recogniser_matches_the_generators_doc_filenames() -> None:
    """The diff's filebases must be exactly the generator's DOC_FILES, slugged.

    keap_docs_gen mints `<anchor>.<filebase>-<stub>` where filebase is the
    slugified filename. If someone adds RUNBOOK.md to DOC_FILES and not here,
    every runbook node starts reading as organ-invented divergence.
    """
    diff = _load(DIFF, "cortex_corpus_diff")
    gen = _load(GEN, "keap_docs_gen")
    expected = tuple(sorted(f.rsplit(".", 1)[0].lower() for f in gen.DOC_FILES))
    assert tuple(sorted(diff._DOC_FILEBASES)) == expected, (
        f"cortex-corpus-diff._DOC_FILEBASES {diff._DOC_FILEBASES} no longer matches "
        f"keap_docs_gen.DOC_FILES {gen.DOC_FILES}; doc nodes the diff does not "
        "recognise are counted as taxonomy divergence and block agreement forever"
    )


def test_recogniser_partitions_doc_nodes_from_self_model_nodes() -> None:
    """Doc nodes in, service/stack/root nodes out — the measured partition."""
    diff = _load(DIFF, "cortex_corpus_diff")
    for node in (
        "nos.voip.freepbx.readme-quick-reference",
        "nos.voip.freepbx.skills-freepbx-skills",
        "nos.iiab.keap.agents-keap-agent-definition",
    ):
        assert diff._is_doc_node(node), f"{node} is a doc node and must be recognised"
    for node in (
        "nos", "nos.voip", "nos.voip.freepbx",          # the self-model KEAP shares
        "nos.iiab.keap.credential",                      # a generated non-doc child
        "01.04.02",                                      # canonical taxonomy
    ):
        assert not diff._is_doc_node(node), (
            f"{node} is NOT documentation; excluding it would hide real divergence"
        )


def test_exclusion_is_reported_rather_than_silent() -> None:
    """A withdrawn population a reader cannot see is a lie of omission."""
    src = DIFF.read_text()
    assert "organ-docs-corpus" in src, "the docs exclusion lost its finding verdict"
    block = src.split("organ-docs-corpus", 1)[1][:1200]
    assert "count" in block and "sample" in block, (
        "the docs finding must carry the count and a sample — an exclusion nobody "
        "can size is indistinguishable from a corpus that never had those nodes"
    )
    assert "organRowsAfterExclusion" in block, (
        "the adjusted row count must be published, or the taxonomy row silently "
        "disagrees with the organ's own /health"
    )


def test_only_the_organ_side_is_ever_excluded() -> None:
    """If doc ids ever appear in KEAP, that is real and must not be swallowed.

    The exclusion is deliberately one-directional: the organ generating docs is
    by design, KEAP holding them would mean something fed it a corpus it does
    not own — a finding, not an exemption.
    """
    src = DIFF.read_text()
    seg = src.split("docs_only = ", 1)[1].split("out.append", 1)[0]
    assert "t.onlyOrgan" in seg and "t.onlyKeap" not in seg, (
        "the docs exclusion must apply to onlyOrgan only; excluding them from "
        "onlyKeap would hide KEAP ingesting a corpus it does not own"
    )


def test_a_truncated_id_listing_never_manufactures_divergence() -> None:
    """Two capped pages must not be subtracted from each other.

    Measured 2026-07-27: both /agent/v1/captures routes hard-cap at 50 rows
    whatever limit is asked for, and the two implementations order differently.
    Diffing those pages reported onlyKeap=45 / onlyOrgan=45 / both=5 over two
    stores holding the SAME 128 rows, and the harness billed `fanout-partial` to
    a fan-out that had just delivered 128 of 128 successfully.

    A ceiling means the check did not run: compare counts, publish the ceiling,
    accuse nobody — and do not read it as agreement either.
    """
    diff = _load(DIFF, "cortex_corpus_diff")
    t = diff._id_table(
        "api_taxonomy_metadata",
        ["a", "b", "c"], ["c", "d", "e"],       # two disjoint-ish "pages"
        128, 128,
        ceiling="/agent/v1/captures takes no offset",
    )
    assert t.onlyKeap == [] and t.onlyOrgan == [], (
        "a truncated listing was subtracted anyway — this is the fabricated "
        "divergence that blamed the feeder"
    )
    assert t.comparable is False, "a ceiling must not read as a comparable id set"
    assert t.ids_agree is False, (
        "an unmeasured id set must not read as agreement either — the harness "
        "does not publish an OK for a check that did not run"
    )
    assert t.counts_agree is True, "counts are still comparable under a ceiling"

    # …and without a ceiling the diff must still work normally.
    t2 = diff._id_table("x", ["a", "b"], ["b", "c"], 2, 2)
    assert t2.onlyKeap == ["a"] and t2.onlyOrgan == ["c"] and t2.comparable is True
