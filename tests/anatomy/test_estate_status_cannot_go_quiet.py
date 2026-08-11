"""Anatomy gate: the state reader may not answer calmly when it did not look.

`tools/estate-status.py` exists because one session made the same mistake three
times on 2026-08-10 — hand-deriving "what is true now" from a partial source
(a local ref nobody fetched, one layer of a two-layer config, a checkout that was
three releases behind the deployed organ). A reader written to end that class
fails the moment it renders absence as agreement, so this gate is aimed almost
entirely at its silences rather than its answers.

WHAT IS PINNED, and each one is a rule the survey produced:

  1. FETCH IS THE DEFAULT, and a FAILED fetch does not fall through to a stale
     comparison. An unfetched comparison is worse than none because it looks
     like one.
  2. A FLOATING PIN IS REPORTED, NEVER SCORED AS A MATCH. `lts/*` and `latest`
     cannot disagree with anything, so they can never warn anyone — that is the
     calm-by-absence defect this estate keeps finding in its own gates.
  3. AN UNREADABLE SIDE IS NOT AGREEMENT. Bone and Wing answer their health
     endpoints and omit any version field; the tool must say provenance is
     unanswerable rather than pass them.
  4. THE CONFIG AXIS READS BOTH LAYERS, last wins. This is the exact defect that
     produced "sixteen services are switched off and running" when all sixteen
     were enabled in config.yml.

WHAT THIS GATE CANNOT DO: prove the numbers are right. It runs the tool offline
against the real repo, so it checks SHAPE and REFUSALS. The numbers change every
hour and pinning them here would make this file the fourth stale copy of the
thing the tool was written to stop.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "estate-status.py"


def run(*args: str, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(TOOL), *args],
        capture_output=True, text=True, timeout=timeout, cwd=REPO,
    )


@pytest.fixture(scope="module")
def offline() -> subprocess.CompletedProcess:
    # --no-fetch keeps the suite offline and deterministic; the fetch path's
    # own refusal is asserted from the source below rather than by cutting a
    # network in CI.
    return run("--no-fetch", "--json")


def test_the_tool_runs_and_returns_structured_state(offline) -> None:
    assert offline.returncode in (0, 1, 2), f"unexpected exit {offline.returncode}"
    payload = json.loads(offline.stdout)
    assert payload["lines"], "the reader produced no lines at all — it has gone blind, not quiet"
    axes = {line["axis"] for line in payload["lines"]}
    assert {"repo", "organ", "tool"} <= axes, (
        f"an axis disappeared: got {sorted(axes)}. Each one is a place a fact "
        "about nOS can live, and a missing axis is a place nobody will look."
    )


def test_not_fetching_is_declared_in_the_output() -> None:
    """Rule 1. A comparison against a possibly-stale ref must say so."""
    out = run("--no-fetch").stdout
    assert "NOT FETCHED" in out, (
        "the tool compared against local refs without saying they may be stale. "
        "That is the exact shape of the 2026-08-10 master error: a real-looking "
        "answer derived from a ref nobody had updated."
    )


def test_a_failed_fetch_refuses_rather_than_comparing() -> None:
    """Rule 1's teeth. Falling through to stale refs is the defect, not a fallback."""
    src = TOOL.read_text(encoding="utf-8")
    fetch_block = src[src.index("def axis_repos"): src.index("def axis_organs")]
    assert "NOT compared" in fetch_block and "UNREADABLE" in fetch_block, (
        "axis_repos no longer refuses on a failed fetch. A fetch that fails and "
        "then compares anyway produces a confident wrong answer."
    )


def test_a_floating_pin_is_never_scored_as_agreement(offline) -> None:
    """Rule 2. `lts/*` matching nothing must read as a warning, not a tick."""
    payload = json.loads(offline.stdout)
    floating = [x for x in payload["lines"] if "FLOATING" in x["detail"]]
    assert floating, (
        "no floating pin was reported. default.config.yml declares "
        "node_nvm_version: 'lts/*' — if that stopped being surfaced, either the "
        "pin became real (good, delete this assertion) or the tool went quiet."
    )
    for line in floating:
        assert line["state"] != "ok" or "can never warn you" in line["detail"], (
            "a floating pin rendered as a plain match. It cannot disagree with "
            "anything, so scoring it as agreement is agreement with nothing."
        )
    assert payload["uncomparable"], "floating pins must also be counted, not just printed"


def test_an_organ_that_reports_no_version_is_unreadable_not_ok(offline) -> None:
    """Rule 3. Reachable is not the same as identified."""
    payload = json.loads(offline.stdout)
    silent = [x for x in payload["lines"]
              if x["axis"] == "organ" and "no version" in x["detail"]]
    for line in silent:
        assert line["state"] == "unreadable", (
            f"organ {line['subject']} answers but reports no version, and the "
            "tool scored it as fine. Provenance was unanswerable, which is a "
            "finding — Bone and Wing are the live example."
        )


def test_absence_is_never_summarised_as_agreement() -> None:
    """The sentence this whole estate keeps having to relearn."""
    out = run("--no-fetch").stdout
    assert "Absence of a comparison is not agreement." in out, (
        "the summary line lost its disclaimer. A reader that prints "
        "'0 disagreements' after skipping half the axes has told a comforting lie."
    )


@pytest.mark.parametrize("flag", [
    "install_gitlab",    # default false, config.yml true — the inverted verdict
    "install_mailpit",   # default true, config.yml false — the one real case
])
def test_the_config_axis_reads_every_layer(flag: str) -> None:
    """Rule 4, pinned on the two flags that produced the wrong answer.

    TWO DEFECTS OF ITS OWN, both found by CI on 2026-08-11 and both worth
    naming because each is a way a gate can be wrong while looking right:

    1. `"config.yml=" in out` is satisfied by the substring inside
       `"default.config.yml="`. The check for the SECOND layer passed even
       when only the first was read — it could never have failed.
    2. `config.yml` is gitignored, so CI resolves one layer where the operator
       resolves two. Asserting a sentence the tool only printed for two layers
       made this test pass locally and fail on the runner, for no defect.

    So: the committed layer is required unconditionally, the operator's layer is
    required only where it exists, and the substring trap is closed by anchoring
    the match to the start of a token.
    """
    out = run("--config", flag).stdout
    assert "default.config.yml=" in out, (
        f"resolving {flag} did not read the committed default at all."
    )
    if (REPO / "config.yml").exists():
        assert re.search(rf"(?<![.\w]){re.escape('config.yml')}=", out), (
            f"resolving {flag} did not show the operator's config.yml layer. "
            "Reading the committed default alone is what turned sixteen enabled "
            "services into 'switched off but running', and hid the one that "
            "really was off. (Anchored so that 'default.config.yml=' cannot "
            "satisfy this by accident — it did, silently, until 2026-08-11.)"
        )
    assert "the LAST layer wins" in out, (
        "the precedence direction is no longer stated. It must print whether or "
        "not a second layer exists: the reader looking at ONE line is the one "
        "who cannot see the rule working."
    )
    assert re.search(r"==>\s*\S+", out), "no resolved verdict was printed"


def test_a_role_default_is_a_layer_too() -> None:
    """The blind spot found while releasing KEAP v1.40.1.

    `keap_repo_ref` lives only in `roles/pazny.keap/defaults/main.yml` and the
    tool answered "declared in no layer" — which reads as "nobody sets this"
    about the variable that decides which git ref the cortex is BUILT from. It
    refused rather than guessed, so it was never dishonest; it was just no use
    to the person asking.
    """
    out = run("--config", "keap_repo_ref").stdout
    assert "declared in no layer" not in out, (
        "keap_repo_ref reads as undeclared. It is declared in a role default, "
        "which outranks nothing and is still where the value comes from."
    )
    assert "roles/" in out and "defaults/main.yml" in out, (
        "the resolved trail does not name the role default it came from. A "
        "value without its source is the thing this tool exists to stop."
    )


def test_claude_md_points_at_the_tool_rather_than_restating_it() -> None:
    """A doc that restates state is a doc that drifts; that is the whole thesis."""
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "tools/estate-status.py" in text, (
        "CLAUDE.md no longer points at the state reader. The estate's own "
        "precedent is the security queue: 'This line no longer carries the "
        "numbers — ask instead: tools/rem-status.py'."
    )
    assert "repo is not the running system" in text.lower(), (
        "the repo-vs-runtime split lost its section. It is the fact that makes "
        "a deployed organ legitimately differ from the checkout, and it was "
        "written nowhere until 2026-08-10."
    )
