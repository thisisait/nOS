"""Gate — the queue-vs-running comparison may recover a version, never guess one.

`fix_version` is written for a human, so it is a sentence as often as a version.
`numeric()` refuses all of it on the correct ground that prose beginning with a
number is prose — and measured 2026-08-22 that refusal left 49 of 173 pairs
unjudged, including a whole class where the estate was demonstrably past its fix
and the row was still open, invisible because of a trailing plus sign.

`read_fix()` recovers exactly two extra shapes and nothing else:

    "1.24.7+"                          a FLOOR
    "8.6.3 (re-pin off EOL 8.0 …)"     a version with DELIMITED commentary
    "version-6.6.3 (security floor)"   the same, with the tag prefix firefly uses

THE ASYMMETRY THIS PINS. A skip is honest; a false contradiction is not. This
tool prints "skips are not agreements" on every run precisely because it would
rather say nothing than say something wrong, and it has been burned in the other
direction before: a prefix match once read REM-129's "6.8.6 / 6.9.5 / 7.0.2
(none dockerized …)" as 6.8.6 and filed a contradiction against a row that says
none of those versions ships in a container.

So the tests below are mostly REFUSALS. Widening the extractor is allowed; doing
it by loosening the delimiter is what this stops.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def ds():
    spec = importlib.util.spec_from_file_location(
        "discovery_scan_under_test", REPO / "tools/discovery-scan.py")
    mod = importlib.util.module_from_spec(spec)
    # The module defines dataclasses, which resolve annotations through
    # sys.modules — importing it without registering raises AttributeError.
    sys.modules["discovery_scan_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── what it must read ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,core,is_floor", [
    ("1.24.7", (1, 24, 7), False),
    ("v3.7.10", (3, 7, 10), False),
    ("1.24.7+", (1, 24, 7), True),
    ("10.10.7+", (10, 10, 7), True),
    ("2026.3.02+", (2026, 3, 2), True),
    ("8.6.3 (re-pin off EOL 8.0 branch)", (8, 6, 3), False),
    ("7.0.2 (dockerized 2026-08-02)", (7, 0, 2), False),
    ("version-6.6.3 (security floor) -- recommend version-6.6.4", (6, 6, 3), False),
])
def test_it_reads_the_shapes_it_claims(ds, raw, core, is_floor):
    got = ds.read_fix(raw)
    assert got is not None, f"read_fix({raw!r}) returned None"
    version, floor = got
    assert version.core == core, f"{raw!r} -> {version.core}, want {core}"
    assert floor is is_floor, f"{raw!r} floor={floor}, want {is_floor}"


# ── what it must refuse ────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "latest",
    "latest (2.27+)",
    "n/a (config change)",
    "n/a -- configuration, not a version",
    "SEC-02 gate (arch mitigation)",
    "hardening only (no CVE; pin is clean)",
    "config change (traefik_auth_modes.traefik: none -> proxy)",
    "digest pin + post-start version assertion",
    "REM-137.fix_version := 1.27.1 + correct the default.config pin",
    # The measured false positive: three versions and a sentence saying none of
    # them ships in a container. A prefix match read this as 6.8.6.
    "6.8.6 / 6.9.5 / 7.0.2 (none dockerized as of 2026-07-20)",
    # An undelimited continuation is prose, however version-shaped its head.
    "1.2.3 or later if you can manage it",
    "2.44 and above",
])
def test_it_refuses_everything_else(ds, raw):
    assert ds.read_fix(raw) is None, (
        f"read_fix({raw!r}) produced a version. A wrong extraction here files a "
        f"FALSE contradiction into the roadmap, which is the one outcome this "
        f"tool's precision rule forbids — skipping is the honest answer."
    )


def test_a_digest_tag_is_still_unreadable(ds):
    """paperclip runs `sha-b9a80dc`. There is no version in it to recover."""
    assert ds.read_tag("sha-b9a80dc") is None
    assert ds.read_tag("latest") is None


def test_the_tag_reader_allows_only_the_version_prefix(ds):
    """firefly tags `version-6.2.21`; nothing else gets a prefix exemption."""
    v = ds.read_tag("version-6.2.21")
    assert v is not None and v.core == (6, 2, 21)
    assert ds.read_tag("release-6.2.21") is None
    assert ds.read_tag("build-42") is None


def test_a_digest_shaped_row_is_refused_by_name(ds):
    """REM-188's shape: "11.8.8 (re-pull)" — satisfying the version is the
    row's PREMISE, not its remedy ("SAME SEMVER, DIFFERENT IMAGE"). Comparing
    versions on it manufactured "already runs 11.8.8 >= 11.8.8 (re-pull)",
    a category error measured live on 2026-08-25. The probe must skip these
    with a named reason before `read_fix` ever sees them.
    """
    hit = ["11.8.8 (re-pull)",
           "n/a (config change) -- record deployed digests",
           "pin by digest",
           "same-semver base-layer refresh"]
    miss = ["8.6.3 (re-pin off EOL 8.0 branch)",   # re-PIN is a version act
            "version-6.6.3 (security floor) -- recommend version-6.6.4",
            "19.2.2-ce.0 (or 18.11.9-ce.0 for the non-security regression fixes only)"]
    for raw in hit:
        assert ds._DIGEST_SHAPED.search(raw), f"digest shape not recognised: {raw!r}"
    for raw in miss:
        assert not ds._DIGEST_SHAPED.search(raw), (
            f"{raw!r} wrongly classed as digest-shaped — that would silence a "
            f"version comparison this probe is allowed to make"
        )
    src = (REPO / "tools/discovery-scan.py").read_text(encoding="utf-8")
    assert "row wants a digest comparison" in src, (
        "the digest refusal must be a NAMED skip reason, not the generic bucket"
    )


def test_security_floor_outranks_fix_version_prose(ds):
    """REM-159's lesson: one fix_version carried a security floor AND a
    regression floor, and the closing pass picked the branch the row's own
    text disclaims. When a row carries `security_floor`, the probe must read
    that field and refuse the row if it is not strictly readable — never fall
    back to guessing at the prose.
    """
    src = (REPO / "tools/discovery-scan.py").read_text(encoding="utf-8")
    assert 'item.get("security_floor")' in src, (
        "the probe no longer consults security_floor — a prose fix_version "
        "naming two versions is back to being a coin toss"
    )
    assert "security_floor present but not strictly readable" in src, (
        "an unreadable security_floor must SKIP, not fall back to the prose"
    )
    # The field itself parses with the same strict reader — a suffixed exact
    # version is readable (the suffix is carried, not discarded), and cores
    # that differ decide outright, so "18.11.9-ce.0" < "19.2.2-ce.0" holds.
    v = ds.read_fix("19.2.2-ce.0")
    assert v is not None and v[0].core == (19, 2, 2)
    have = ds.read_tag("18.11.9-ce.0")
    assert have is not None
    assert ds.compare(have, v[0]) == -1


def test_a_floor_is_not_branched_on(ds):
    """The comparison must stay inequality-based rather than special-casing.

    The first cut of this work added `if is_floor and status == 'resolved':
    continue`, which suppressed a REAL finding — a resolved row whose estate sits
    BELOW its floor means the fix never landed. Both branches already test `< 0`
    and `>= 0`, so over-shooting a floor was never reported in the first place.
    """
    src = (REPO / "tools/discovery-scan.py").read_text(encoding="utf-8")
    assert 'if is_floor and status ==' not in src, (
        "a floor must not gate the resolved branch: resolved + below-floor is a "
        "contradiction, and suppressing it hides a fix that never reached the estate"
    )
    assert 'status == "resolved" and verdict < 0' in src
    assert 'status == "pending" and verdict >= 0' in src
