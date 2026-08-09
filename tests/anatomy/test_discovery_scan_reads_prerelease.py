"""Anatomy gate: the contradiction scanner must not swallow a prerelease suffix.

`tools/discovery-scan.py` exists to catch records that disagree with the running
estate. On 2026-08-09 it was producing one of its own:

    ! REM-187 still pending; iiab-rustfs-1 already runs 1.0.0-beta.11 >= 1.0.0-beta.12

`beta.11 >= beta.12` is false. The regex matched the suffix in a non-capturing
group and nothing read it back, so only the release core was compared and both
tags reduced to (1, 0, 0). Two roadmap rows were filed from that arithmetic.

THE NOISY DIRECTION IS THE ONE THAT GOT NOTICED; the silent one is worse. A
swallowed suffix makes a BEHIND container read as EQUAL, so probe A stops
reporting a pin that never reached its container and probe B stops reporting a
`resolved` row whose fix never landed — for every prerelease-tagged component.
rustfs, which is where the backups go, is exactly such a component.

The second half of this gate pins the REFUSAL. Reading the suffix is not a
licence to order every suffix: comparing `6.0.0-dev` against `6.0.0` picks a
side in a question only the vendor's tagging convention answers, and the first
draft of the fix did exactly that — it turned two false alarms into two
different false alarms. The tool's own precision rule is that an ambiguous
comparison SKIPS, and a skip is counted and printed, never silently scored as
agreement.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCANNER = REPO / "tools" / "discovery-scan.py"


def _scanner():
    spec = importlib.util.spec_from_file_location("discovery_scan_under_test", SCANNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registering before exec: @dataclass resolves annotations through
    # sys.modules and raises AttributeError on a module that is not there yet.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scan():
    return _scanner()


def _cmp(scan, a: str, b: str):
    va, vb = scan.numeric(a), scan.numeric(b)
    assert va is not None, f"{a!r} did not parse as a version"
    assert vb is not None, f"{b!r} did not parse as a version"
    return scan.compare(va, vb)


# ── the defect itself ───────────────────────────────────────────────────────

def test_the_rustfs_pair_that_produced_the_false_contradiction(scan) -> None:
    assert _cmp(scan, "1.0.0-beta.11", "1.0.0-beta.12") == -1, (
        "1.0.0-beta.11 is BEHIND 1.0.0-beta.12. This is the exact pair the scan "
        "reported as `>=`, filing two roadmap rows against a queue that was right."
    )
    assert _cmp(scan, "1.0.0-beta.12", "1.0.0-beta.11") == 1


def test_a_suffix_is_not_discarded(scan) -> None:
    """The mechanism, pinned so the gate cannot outlive its reason."""
    a, b = scan.numeric("1.0.0-beta.11"), scan.numeric("1.0.0-beta.12")
    assert a != b, (
        "two different prerelease tags parsed to the same value — the suffix is "
        "being swallowed again, which is how a BEHIND container reads as EQUAL."
    )


@pytest.mark.parametrize(("lo", "hi"), [
    ("1.0.0-alpha.90", "1.0.0-beta.11"),   # channel order
    ("1.0.0-beta.9", "1.0.0-rc.1"),
    ("1.0.0-beta", "1.0.0-beta.1"),        # a longer identifier list outranks
    ("1.0.0-beta.2", "1.0.0-beta.10"),     # numeric ids compare numerically
    ("1.0.0-beta.11", "1.1.0-beta.1"),     # a differing core decides outright
])
def test_known_prerelease_ordering(scan, lo: str, hi: str) -> None:
    assert _cmp(scan, lo, hi) == -1, f"{lo} should sort below {hi}"
    assert _cmp(scan, hi, lo) == 1


def test_release_cores_are_zero_padded(scan) -> None:
    """2.44 and 2.44.0 are the same version; portainer is tagged both ways."""
    assert _cmp(scan, "2.44", "2.44.0") == 0
    assert _cmp(scan, "v1.2.3", "1.2.3") == 0


# ── the refusal ─────────────────────────────────────────────────────────────

def test_a_lone_suffix_is_not_comparable(scan) -> None:
    """`6.0.0-dev` vs `6.0.0` — semver says below, Docker convention often above.

    Superset runs `6.0.0-dev` and two resolved rows name `6.0.0`. The first
    draft of the prerelease fix scored that as BEHIND and reported both rows as
    lies. Nobody measured which way that tag actually points, so the honest
    answer is a skip.
    """
    assert _cmp(scan, "6.0.0-dev", "6.0.0") is None
    assert _cmp(scan, "6.0.0", "6.0.0-dev") is None


def test_unknown_channels_are_not_ranked_lexically(scan) -> None:
    """`dev` < `nightly` is alphabetical, not a fact about builds."""
    assert _cmp(scan, "1.0.0-dev.4", "1.0.0-nightly.2") is None


def test_same_unknown_channel_still_compares(scan) -> None:
    """Refusing to rank channels is not refusing to count within one."""
    assert _cmp(scan, "1.0.0-dev.4", "1.0.0-dev.9") == -1


def test_prose_and_floating_tags_still_skip(scan) -> None:
    for value in (
        "6.8.6 / 6.9.5 / 7.0.2 (none dockerized as of 2026-07-20)",
        "latest",
        "main",
        "",
    ):
        assert scan.numeric(value) is None, (
            f"{value!r} parsed as a version. A leading-numeric or free-text match "
            "manufactures contradictions out of punctuation — REM-129 is the "
            "worked example."
        )


def test_an_unreadable_comparison_is_counted_as_a_skip(scan) -> None:
    """A skip must be visible. `compared` counts judgements, not attempts."""
    source = SCANNER.read_text(encoding="utf-8")
    assert source.count('res.skip("prerelease suffix not comparable') == 2, (
        "both probes must report an unreadable prerelease as a skip. An "
        "uncounted refusal is indistinguishable from agreement, and the summary "
        "line's promise — 'Skips are not agreements' — is what makes that safe."
    )
