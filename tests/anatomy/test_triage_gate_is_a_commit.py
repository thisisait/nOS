"""Discovery may file work. It may not authorise its own work.

THE PROBLEM, decided 2026-08-04. The estate is growing two loops with opposite
failure modes:

  * DISCOVERY finds contradictions and files them. It fails by NOISE (a
    confident finding that is wrong) and by SILENCE (missing what is there).
  * IMPLEMENTATION takes a filed item and changes the estate. It fails by BLAST
    RADIUS.

They are only safe as two loops if the transition between them requires
something discovery cannot do. Otherwise a hallucinated finding walks straight
into a merged change and the pair collapses back into one loop with extra steps.

WHY THE GATE IS A COMMIT AND NOT A STATUS. A status column is DATA, and the
discovery loop writes data — it POSTs roadmap rows to KEAP over HTTP. Any lane
it can write, it can promote itself into, so a status gate is a convention
rather than a mechanism. A committed workflow spec under `.claude/workflows/`
is on the other side of a boundary discovery has no path across: it writes rows
through an API and has no way to author, commit or push a file. That asymmetry
is structural, and it is the whole reason `.claude/workflows/` was taken out of
.gitignore earlier the same day.

SO: a roadmap row is a PROPOSAL. A committed workflow spec naming that row is
the AUTHORISATION. `meta.implements` carries the binding, and its presence in
git is the gate — not the field's value.

WHAT THIS GATE CHECKS
  1. every `implements` resolves to a roadmap slug that actually exists
  2. no two workflows claim the same row (two specs racing on one item)
  3. the roadmap writer and the workflow specs stay on opposite sides — the
     tool that POSTs rows must not also write under .claude/workflows/

WHAT IT CANNOT CHECK: whether the human who committed the spec actually read
the row. Nothing static can. It checks that the crossing left a trace in a
place discovery cannot reach, which is the property the two-loop split needs.

Analysis and review workflows carry no `implements` and are not affected — they
change nothing, so there is nothing to authorise.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".claude/workflows"
SEEDER = REPO / "tools/roadmap-seed.py"
# Every tool that FILES roadmap rows must sit on discovery's side of the
# boundary. discovery-scan.py is the loop that actually files findings, so it
# is the one that matters most: if it could author a workflow spec it could
# authorise its own observation, and the two loops would be one.
ROW_WRITERS = [SEEDER, REPO / "tools/discovery-scan.py"]

_IMPLEMENTS = re.compile(r"^\s*implements:\s*'([a-z0-9-]+)'", re.MULTILINE)
# The seeder declares rows two ways: row("slug", …) and release tuples.
_ROW_SLUG = re.compile(r"""row\(\s*["']([a-z0-9-]+)["']""")
_REL_SLUG = re.compile(r"""^\s*\(["']([a-z0-9-]+)["'],""", re.MULTILINE)


def _workflows() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.js")) if WORKFLOWS.is_dir() else []


def _declared_slugs() -> set[str]:
    src = SEEDER.read_text(encoding="utf-8")
    return set(_ROW_SLUG.findall(src)) | set(_REL_SLUG.findall(src))


def _bindings() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for p in _workflows():
        m = _IMPLEMENTS.search(p.read_text(encoding="utf-8"))
        if m:
            out[p] = m.group(1)
    return out


def test_the_roadmap_row_source_is_readable():
    """Positive control — an unreadable seeder makes everything below vacuous."""
    assert SEEDER.is_file(), "tools/roadmap-seed.py is gone; this gate is blind"
    assert len(_declared_slugs()) > 10, (
        "the seeder declares almost no slugs — the extraction pattern has "
        "probably rotted, and every binding below would 'resolve' against an "
        "empty set"
    )


def test_at_least_one_workflow_declares_what_it_implements():
    """Otherwise the whole convention is unexercised and silently dead."""
    assert _bindings(), (
        "no workflow declares `implements`. The triage binding exists only in "
        "doctrine, so nothing connects a committed spec to the row it "
        "authorises."
    )


@pytest.mark.parametrize("path", sorted(_bindings()), ids=lambda p: p.name)
def test_every_implements_resolves_to_a_real_row(path):
    """A spec authorising a row that does not exist authorises nothing."""
    slug = _bindings()[path]
    declared = _declared_slugs()
    assert slug in declared, (
        f"{path.name} declares implements: '{slug}', which is not a roadmap "
        f"slug. Either the row was never filed — in which case the work skipped "
        f"discovery entirely and there is nothing to triage — or the slug is "
        f"misspelled and the binding silently points at nothing."
    )


def test_no_two_workflows_claim_the_same_row():
    """Two specs racing on one item is an unresolvable merge, not parallelism.

    EXCEPT where the row is explicitly a multi-step item: the three
    anatomy-view workflows all implement `face-anatomy` by design, in a fixed
    order. So this asserts the weaker, true property: a row may have several specs
    only if their names share a prefix, i.e. they are visibly one family.
    """
    counts = Counter(_bindings().values())
    for slug, n in counts.items():
        if n < 2:
            continue
        names = sorted(p.stem for p, s in _bindings().items() if s == slug)
        prefix = names[0].rsplit("-", 1)[0]
        assert all(x.startswith(prefix) for x in names), (
            f"roadmap row '{slug}' is claimed by {n} unrelated workflows: "
            f"{names}. Two independent specs for one item will each assume they "
            f"own it."
        )


@pytest.mark.parametrize("writer", ROW_WRITERS, ids=lambda p: p.name)
def test_the_roadmap_writer_cannot_write_workflow_specs(writer):
    """The asymmetry itself, as the thing that must stay true.

    Discovery's write path is HTTP to KEAP. If the same tool could also author
    files under .claude/workflows/, the gate would be one refactor away from
    being self-serviceable.
    """
    if not writer.is_file():
        pytest.skip(f"{writer.name} not present")
    src = writer.read_text(encoding="utf-8")

    # NOT "does the string appear" — the first version of this assertion
    # forbade `.claude/workflows` anywhere in the file and immediately tripped
    # on a row's `refs` field, which POINTS AT the authorising spec. That is a
    # citation, and citing the spec is the useful thing `refs` is for. A gate
    # that fires on a reference is noise, and noise gets muted.
    #
    # The property is about WRITES. Filing a row is an HTTP POST; if this tool
    # could also author files, the boundary would be one refactor from
    # self-serviceable.
    # WORD BOUNDARIES, because `urlopen(` contains `open(` and the first
    # version of this check flagged the seeder's own HTTP call as a filesystem
    # write. Third substring false-positive in one day's gates; matching a bare
    # token inside a larger identifier is how a gate ends up describing
    # something other than what it names.
    # `open(` must be the BARE BUILTIN, not a method call. 2026-08-11: probe G
    # gave discovery-scan a no-redirect `opener.open(req)` — an HTTP call — and
    # `\bopen\(` flagged it as a filesystem write. That is the FOURTH
    # substring false-positive in this family, and this time the gate's own
    # comment three lines up had already recorded the lesson for a different
    # token. A word boundary does not exclude a preceding dot; a lookbehind does.
    writes = [v for v in (r"(?<![.\w])open\(", r"\bwrite_text\b",
                          r"\bos\.makedirs\b", r"\bshutil\.")
              if re.search(v, src)]
    assert not writes, (
        f"{writer.name} performs filesystem writes ({writes}). The tool "
        f"that FILES roadmap rows must not be able to author the specs that "
        f"AUTHORISE them — its only output should be HTTP POSTs to the table, "
        f"or discovery can promote its own findings."
    )
    assert "urllib" in src, (
        f"{writer.name} no longer talks HTTP at all — if row filing moved to a "
        "different mechanism, this gate is checking a path nobody uses"
    )
