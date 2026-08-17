"""The public page's typefaces: small enough, licensed, and complete.

MEASURED 2026-08-17, the day the page went live. A visitor's first request
transferred 1,991,929 bytes. 1,954,484 of them were typeface and 27,561 were
the page — for a page whose whole job is somebody's first thirty seconds,
often on a phone. The three faces are now Latin subsets (558,540 B, 71%
smaller), cut by `files/anatomy/apex/subset-fonts.py`.

Three ways that can rot, and each has a test here:

1. SIZE — someone re-vendors an upstream binary and the page silently goes
   back to two megabytes. Nothing breaks; it just gets slow for strangers,
   who do not report it.

2. LICENCE — two of the three faces declare Reserved Font Name 'Source' in
   their own copyright string. A subset is a Modified Version and OFL clause 3
   forbids a Modified Version from carrying the reserved name, so they ship
   renamed. A future re-subset that forgets the rename is a licence
   violation that looks exactly like a working font.

3. COVERAGE — the subset carries the glyphs the page needs TODAY. The page
   is generated from a ruling the operator edits; a new phrase with a
   character outside the cut set renders as tofu on the public site and on
   nobody's screen here. So the test reads the BUILT page and demands every
   codepoint of it from the served faces — plus a narrower test for the two
   characters only one face draws.

The size and coverage tests pull in opposite directions on purpose: one
punishes a font that carries too much, the other a font that carries too
little. Neither can be satisfied by loosening the other.
"""

from __future__ import annotations

import pathlib
import re
import sys
import tempfile

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
APEX = REPO / "files/anatomy/apex"
FONTS = APEX / "assets" / "fonts"
UPSTREAM = FONTS / "upstream"
CSS = APEX / "assets" / "ait.css"

fontTools = pytest.importorskip("fontTools", reason="fontTools is the subsetter's own dependency")

from fontTools.ttLib import TTFont  # noqa: E402

# The ceiling is ~10% above what the current cut measures, so ordinary
# glyph-set growth passes and a re-vendored full binary (1.2 MB serif) does
# not. It is a tripwire, not a budget to spend down to.
PER_FACE_CEILING = 400_000
TOTAL_CEILING = 620_000

_RFN = re.compile(r"Reserved Font Name\s*[‘'\"]?([A-Za-z0-9 ]+?)[’'\".]", re.I)


def served_faces() -> list[pathlib.Path]:
    """The faces that reach a visitor: everything in fonts/ except upstream/."""
    return sorted(p for p in FONTS.glob("*.ttf") if p.parent == FONTS)


def _built_text() -> str:
    """Build the page into a throwaway directory and return every text byte.

    PREVIEW mode deliberately — this test must work whether or not the
    ruling is signed.
    """
    sys.path.insert(0, str(APEX))
    import build

    with tempfile.TemporaryDirectory() as tmp:
        out = build.build(pathlib.Path(tmp) / "dist")
        return "".join(
            p.read_text(encoding="utf-8")
            for p in sorted(out.rglob("*"))
            if p.is_file() and p.suffix in {".html", ".css", ".json"}
        )


def test_the_sweep_finds_the_faces():
    """Positive control — an empty sweep makes every check below vacuous."""
    faces = served_faces()
    assert len(faces) == 3, f"expected 3 served faces, found {[f.name for f in faces]}"
    assert UPSTREAM.is_dir(), (
        "fonts/upstream/ is gone — the subsets can no longer be reproduced, "
        "and a coverage failure would have nothing to re-cut from."
    )


def test_no_face_is_the_full_upstream_binary():
    total = 0
    for face in served_faces():
        size = face.stat().st_size
        total += size
        assert size <= PER_FACE_CEILING, (
            f"{face.name} is {size:,} B, over the {PER_FACE_CEILING:,} B ceiling. "
            "A full upstream binary is being served: re-run "
            "`python3 files/anatomy/apex/subset-fonts.py`."
        )
    assert total <= TOTAL_CEILING, (
        f"the served faces total {total:,} B, over {TOTAL_CEILING:,}. The page "
        "itself is ~28 kB; the typefaces are the whole of a stranger's wait."
    )


def test_a_reserved_font_name_is_never_the_name_we_ship():
    """OFL clause 3. The original copyright notice is RETAINED (clause 1) — what may not
    travel is the reserved name as this font's own name."""
    checked = 0
    for face in served_faces():
        font = TTFont(str(face), lazy=True)
        notice = font["name"].getDebugName(0) or ""
        names = [font["name"].getDebugName(i) or "" for i in (1, 4, 6, 16, 17)]
        font.close()

        assert notice.strip(), f"{face.name} carries no copyright notice at all"
        hit = _RFN.search(notice)
        if not hit:
            continue
        checked += 1
        reserved = hit.group(1).strip().lower()
        offenders = [n for n in names if reserved in n.lower()]
        assert not offenders, (
            f"{face.name} declares Reserved Font Name {reserved!r} and still "
            f"names itself {offenders!r}. A subset is a Modified Version; OFL "
            "clause 3 forbids it from carrying the reserved name. Add a rename to "
            "RENAME in subset-fonts.py and re-cut."
        )
    assert checked >= 2, (
        f"only {checked} served face declares a Reserved Font Name; on "
        "2026-08-17 two did (both Adobe, 'Source'). If the faces changed, "
        "re-read this test's premise rather than lowering the number."
    )


def test_the_stylesheet_points_at_faces_that_exist():
    css = CSS.read_text(encoding="utf-8")
    refs = re.findall(r'url\("fonts/([^"]+)"\)', css)
    assert refs, "the stylesheet declares no @font-face src — the page has no vendored type"
    for ref in refs:
        assert (FONTS / ref).is_file(), (
            f"ait.css points at fonts/{ref}, which is not vendored. The browser "
            "would fall back silently and nobody here would see it."
        )
    served = {p.name for p in served_faces()}
    assert set(refs) == served, (
        f"the stylesheet uses {sorted(set(refs))} but {sorted(served)} are "
        "served — an unused face is dead weight, a missing one is a fallback."
    )


def test_every_character_the_page_renders_exists_in_some_face():
    """At least one served face must have every codepoint the page uses.

    Not EVERY face: the first cut of this test demanded that, and it failed
    honestly — the disclosure markers ▸/▾ live only in the mono, because
    Open Sans and Source Serif 4 simply do not draw them upstream. A subset
    cannot invent a glyph. Which face renders which run is a question about
    the cascade, so the two markers get their own test below rather than a
    blanket rule that would have to be either too strict or vacuous.
    """
    text = _built_text()
    needed = {ord(ch) for ch in text if ch not in "\n\r\t"}

    covered: set[int] = set()
    for face in served_faces():
        font = TTFont(str(face), lazy=True)
        covered |= set(font.getBestCmap())
        font.close()

    missing = sorted(needed - covered)
    assert not missing, (
        f"no served face has {len(missing)} codepoint(s) the built page uses: "
        f"{[hex(c) + ' ' + chr(c) for c in missing[:8]]}. They render from "
        "whatever the visitor's system happens to own, or as tofu. Re-run "
        "subset-fonts.py; if the glyph is absent upstream too, change the "
        "character rather than shipping a page that depends on a stranger's "
        "font stack."
    )


def test_the_disclosure_markers_come_from_the_face_that_draws_them():
    """▸ and ▾ are the only characters on this page that one face has and the
    others do not. The summary line is set in the mono, which is the face
    that has them — so the dependency holds only while both halves do."""
    css = CSS.read_text(encoding="utf-8")
    markers = re.findall(r'summary::before\s*\{\s*content:\s*"([^"]+)"', css)
    assert markers, "the disclosure markers are gone from the stylesheet — retire this test"
    needed = {ord(ch) for m in markers for ch in m if ch != " "}

    summary_block = re.search(r"summary\s*\{[^}]*\}", css)
    assert summary_block and "var(--code)" in summary_block.group(0), (
        "the disclosure summary is no longer set in the mono face. The "
        f"markers {sorted(chr(c) for c in needed)} exist ONLY there; in the "
        "serif or the sans they fall back to the visitor's system font."
    )

    mono = [f for f in served_faces() if "SourceCodePro" in f.name]
    assert len(mono) == 1, f"cannot identify the mono face among {[f.name for f in served_faces()]}"
    font = TTFont(str(mono[0]), lazy=True)
    covered = set(font.getBestCmap())
    font.close()
    assert needed <= covered, (
        f"the mono subset lost {sorted(hex(c) for c in needed - covered)} — "
        "the disclosure triangles now render from nowhere."
    )


def test_the_coverage_check_can_actually_fail():
    """Mutation control for the test above: a codepoint no Latin subset can
    have must be reported missing, or the check proves nothing."""
    face = served_faces()[0]
    font = TTFont(str(face), lazy=True)
    covered = set(font.getBestCmap())
    font.close()
    assert 0x4E2D not in covered, (
        "a Latin subset claims to cover U+4E2D — the coverage test would pass "
        "against any input and is therefore meaningless."
    )
    assert ord("ř") in covered, (
        "Latin Extended-A is missing from the cut; the declared floor exists "
        "so Czech copy needs no re-subset."
    )


def test_the_stylesheet_asks_for_no_feature_the_cut_dropped():
    """71% of the saving came from dropping OpenType features, not glyphs. A
    stylesheet that later asks for one of the dropped sets gets silence."""
    sys.path.insert(0, str(APEX))
    import importlib.util

    spec = importlib.util.spec_from_file_location("subset_fonts", APEX / "subset-fonts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    kept = {f.lower() for f in module.KEPT_FEATURES}

    css = CSS.read_text(encoding="utf-8")
    asked = {m.lower() for m in re.findall(r'font-feature-settings:[^;]*"(\w{4})"', css)}
    unmet = asked - kept
    assert not unmet, (
        f"ait.css requests OpenType feature(s) {sorted(unmet)} that the subset "
        "dropped. Add them to KEPT_FEATURES and re-cut, or the declaration is "
        "a no-op that reads as working CSS."
    )


def test_the_provenance_never_reaches_the_web_root():
    """fonts/upstream/ is the 1.9 MB the page was trimmed of. Copying it into
    a build would restore the weight at a guessable path."""
    sys.path.insert(0, str(APEX))
    import build

    with tempfile.TemporaryDirectory() as tmp:
        out = build.build(pathlib.Path(tmp) / "dist")
        assert not (out / "assets" / "fonts" / "upstream").exists(), (
            "the build copied fonts/upstream/ into the web root; every full "
            "binary is publicly fetchable and the subsetting bought nothing."
        )
        shipped = sorted(p.name for p in (out / "assets" / "fonts").glob("*.ttf"))
        assert shipped == sorted(p.name for p in served_faces())
