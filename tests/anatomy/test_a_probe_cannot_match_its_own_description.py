"""A roadmap probe may not be satisfied by the text that plans the work.

WHAT HAPPENED, 2026-08-08, within an hour of writing the probe catalogue.
`state/roadmap-probes.yml` gives each roadmap row a command whose exit code
becomes its `verified` verdict. Nine rows came back `confirmed` on the first
run. Five of them were wrong, and all five the same way:

    sec-p1:  grep -rqil "hkdf" tools/ files/anatomy/ roles/   ->  exit 0

The only file in this repository containing the string "hkdf" is
`tools/roadmap-seed.py` — the script that AUTHORS the roadmap row saying HKDF
derivation should be built. The probe did not observe the work; it observed the
plan, and reported the plan as the work.

`sec-p5` matched the same file for the same reason. `loop-forget` matched
`last_attempted_at`, a webhook retry column with nothing to do with the loop
remembering what it tried. `fs-peruser` matched the words "per-user" in three
unrelated plugin manifests.

This is the estate's oldest defect in a new place — the same shape as a gate
matching its own explanatory comment, a doctrine file describing a live
consumer that does not exist, a security tally copied into prose. Something
that describes X is not evidence of X. Here it is worse than usual, because
this catalogue's whole job is to be the independent half of a claim: a probe
that reads the plan makes `verified` a second copy of `status`, and the two
columns exist precisely so they can disagree.

WHAT THIS GATE ENFORCES.

  1. A recursive grep may not search `tools/` or `docs/` — the two trees that
     hold the planning text. Non-recursive uses are untouched: `ls tools/ |
     grep -q agent-eval` reads NAMES, not the contents of the plan.
  2. A probe may not be trivially true.
  3. Every slug in the catalogue must be a row somebody authored, so a typo
     fails here rather than silently verifying nothing.

WHAT IT CANNOT SEE. Whether a probe that passes these rules is actually
DECISIVE — `test -f README.md` is scoped correctly and proves nothing about any
row. That judgement stays with whoever writes the probe. This gate removes the
one failure mode that had already happened five times in one file.
"""

from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
PROBES = REPO / "state/roadmap-probes.yml"
SEEDER = REPO / "tools/roadmap-seed.py"

#: Trees whose job is to describe the work rather than be it.
PLAN_ROOTS = ("tools/", "docs/")

#: A command that exits 0 no matter what the estate looks like.
TRIVIAL = {"true", ":", "exit 0", "test 1 -eq 1", "echo"}


def catalogue() -> dict:
    return yaml.safe_load(PROBES.read_text(encoding="utf-8")) or {}


def commands() -> dict[str, str]:
    """slug -> command, for the entries that actually run something."""
    return {k: v for k, v in catalogue().items() if isinstance(v, str)}


def _grep_is_recursive(tokens: list[str], i: int) -> bool:
    """Does the grep starting at token i carry a recursive flag?"""
    for tok in tokens[i + 1:]:
        if tok in ("|", ";", "&&", "||"):
            break
        if tok.startswith("-") and not tok.startswith("--") and "r" in tok[1:].lower():
            return True
        if tok in ("--recursive", "--dereference-recursive"):
            return True
    return False


def test_a_recursive_grep_never_searches_the_planning_trees():
    offenders: list[str] = []
    for slug, cmd in commands().items():
        try:
            tokens = shlex.split(cmd)
        except ValueError:                       # unbalanced quotes — not our call
            continue
        for i, tok in enumerate(tokens):
            if tok != "grep" or not _grep_is_recursive(tokens, i):
                continue
            # A DIRECTORY under the plan trees is the hazard. A named file is
            # not: `grep -r … tools/scan-runner.sh` reads one artifact, and the
            # first draft of this gate failed exactly that probe — a gate whose
            # own false positive would have pushed a correct probe to be worse.
            roots = [t for t in tokens[i + 1:]
                     if not t.startswith("-") and t.startswith(PLAN_ROOTS)
                     and (REPO / t).is_dir()]
            if roots:
                offenders.append(f"{slug}: searches {', '.join(roots)} recursively")
    assert not offenders, (
        "these probes read the trees that hold the PLAN, so they can be "
        "satisfied by the description of the work instead of the work:\n  "
        + "\n  ".join(offenders)
        + "\n(this is how sec-p1 came back `confirmed` against a repo where the "
          "only occurrence of `hkdf` was the roadmap seeder's own row text)")


def test_no_probe_is_trivially_true():
    trivial = sorted(slug for slug, cmd in commands().items()
                     if cmd.strip() in TRIVIAL or cmd.strip().startswith("echo "))
    assert not trivial, (
        "a probe that cannot fail records a verdict nobody earned: "
        + ", ".join(trivial))


def test_every_probed_slug_is_a_row_someone_authored():
    """Offline half of the catalogue's integrity — the live half is
    `tools/roadmap-verify.py --all`, which refuses slugs the table lacks."""
    # Rows are authored in the PRIVATE seed repo now (dtt-seed-per-row-file), so
    # the seeder no longer inlines slugs. The public, content-free slug index is
    # the offline source of the authored set.
    import yaml
    idx = yaml.safe_load((REPO / "state/roadmap/index.yml").read_text(encoding="utf-8")) or []
    authored = {r["slug"] for r in idx}
    stray = sorted(s for s in catalogue()
                   if s not in authored and not s.startswith("obs-"))
    assert not stray, (
        "the catalogue names rows tools/roadmap-seed.py does not author — a "
        "typo here verifies nothing, quietly: " + ", ".join(stray))


def test_the_unverifiable_entries_carry_a_reason():
    empty = sorted(
        slug for slug, v in catalogue().items()
        if isinstance(v, dict) and not (v.get("unverifiable") or "").strip())
    assert not empty, (
        "`unverifiable` without a reason is `unverified` with extra steps: "
        + ", ".join(empty))
