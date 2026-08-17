#!/usr/bin/env python3
"""Vendor Latin subsets of the apex typefaces, renamed as the OFL requires.

    python3 files/anatomy/apex/subset-fonts.py          # rewrite assets/fonts/
    python3 files/anatomy/apex/subset-fonts.py --check  # verify, write nothing

WHY. Measured on the live page the day it was signed: the first visit to
pazny.eu transferred 1,991,929 bytes, of which 1,954,484 were typefaces and
27,561 were the page. The serif alone was 1.2 MB. This page exists to be
somebody's first thirty seconds with the estate, often on a phone.

woff2 would be the usual answer and is NOT available: its encoder needs the
Brotli python module, absent from every toolchain here, and adding a build
dependency for a font was refused. A subset TTF needs nothing that is not
already on the host, so that is what ships.

THE OFL PART, which is why this is a tool and not a one-liner. Two of the
three faces declare a Reserved Font Name in their own binary:

    Source Code Pro  © 2023 Adobe … with Reserved Font Name 'Source'
    Source Serif 4   © 2014-2021 Adobe … with Reserved Font Name 'Source'

A subset is a Modified Version, and OFL clause 3 forbids a Modified Version from
carrying the reserved name. So the subsets are renamed (the ORIGINAL
copyright notice is retained, as clause 1 requires — retaining the notice is not
the same as using the name). Open Sans declares no reserved name and keeps
its own.

Note the accompanying licence file for the serif did NOT carry the reserved
name while the binary did; the binary is authoritative and the notice was
corrected when this landed.

THE GLYPH SET is not guessed. It is the union of a declared Latin base and
every codepoint the built page actually uses — so a ruling that introduces a
new character is covered here, and `tests/anatomy/test_apex_fonts_are_subset.py`
fails the day the built page needs a glyph the vendored subsets lack.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

APEX = Path(__file__).resolve().parent
FONTS = APEX / "assets" / "fonts"
UPSTREAM = FONTS / "upstream"

# The declared floor: Latin-1, Latin Extended-A (this is what makes Czech,
# Polish and Hungarian copy possible without a re-subset), the punctuation
# and currency blocks, and the soft hyphen / zero-width joiners that HTML
# entities produce. Anything the page uses beyond this is added below.
BASE_RANGES = [
    (0x0000, 0x00FF),   # Basic Latin + Latin-1 Supplement
    (0x0100, 0x017F),   # Latin Extended-A
    (0x2000, 0x206F),   # General Punctuation (— – ' " … ‰ nbsp variants)
    (0x20A0, 0x20BF),   # Currency Symbols
    (0x2190, 0x21FF),   # Arrows
    (0x2212, 0x2212),   # minus
]

# A family carrying a Reserved Font Name MUST be renamed. The mapping is
# explicit and the tool REFUSES a reserved name it has no rename for — a new
# vendored face cannot slip through by being forgotten.
RENAME = {
    "Source Serif 4": "AIT Serif",
    "Source Code Pro": "AIT Mono",
}

_RFN = re.compile(r"Reserved Font Name\s*[‘'\"]?([A-Za-z0-9 ]+?)[’'\".]", re.I)

# The OpenType features kept. This, NOT the glyph count, is what the size
# turned out to hang on: measured on the serif, dropping the exotic feature
# sets (small caps, swashes, alternates, oldstyle figures — none of which
# this page's stylesheet asks for) took it from 546,828 to 314,972 bytes,
# while removing 112 arrow glyphs saved 3,120. So the glyph floor stays
# generous and the feature list is where the restraint is.
#
# Kept: the shaping features a browser applies by default (ccmp/locl/kern/
# liga/clig/calt/rlig, mark/mkmk for combining accents — Latin Extended-A is
# useless without them), plus `case` for the uppercased labels and `tnum`
# for aligned figures. `tests/anatomy/test_apex_fonts_are_subset.py` fails
# if the stylesheet ever requests a feature outside this set.
KEPT_FEATURES = [
    "ccmp", "locl", "kern", "liga", "clig", "calt", "rlig",
    "mark", "mkmk", "case", "tnum",
]


def required_codepoints() -> set[int]:
    """Every codepoint the built page renders, plus the declared base.

    The page is built into a throwaway directory in PREVIEW mode: this tool
    is a developer act and must work before a ruling is signed.
    """
    sys.path.insert(0, str(APEX))
    import build  # noqa: E402  (imported late: it pulls in the projection)

    with tempfile.TemporaryDirectory() as tmp:
        out = build.build(Path(tmp) / "dist")
        text = "".join(
            p.read_text(encoding="utf-8")
            for p in sorted(out.rglob("*"))
            if p.suffix in {".html", ".css", ".json"}
        )

    points = {c for lo, hi in BASE_RANGES for c in range(lo, hi + 1)}
    points |= {ord(ch) for ch in text}
    return points


def reserved_name(font) -> str | None:
    notice = font["name"].getDebugName(0) or ""
    hit = _RFN.search(notice)
    return hit.group(1).strip() if hit else None


def rename_family(font, old: str, new: str) -> None:
    """Rewrite the name-table entries that carry the family name.

    nameID 0 (copyright) is deliberately NOT touched: OFL clause 1 requires the
    notice to travel with the software. What may not travel is the reserved
    name as THIS font's name, which is IDs 1/3/4/6/16/17.

    Both spellings are rewritten. ID 6 is the PostScript name and carries the
    space-less form — 'SourceCodePro-ExtraLight' — so replacing only the
    display family leaves the reserved token sitting in the binary. The gate
    caught exactly that on the first cut.
    """
    forms = [(old, new), (old.replace(" ", ""), new.replace(" ", ""))]
    for record in font["name"].names:
        if record.nameID in (1, 3, 4, 6, 16, 17):
            value = str(record)
            for src, dst in forms:
                if src in value:
                    value = value.replace(src, dst)
            record.string = value


def subset_one(src: Path, points: set[int], write: bool) -> tuple[str, int, int]:
    from fontTools import subset as ftsubset
    from fontTools.ttLib import TTFont

    probe = TTFont(str(src), lazy=True)
    family = probe["name"].getDebugName(16) or probe["name"].getDebugName(1) or ""
    reserved = reserved_name(probe)
    probe.close()

    # A face whose family still contains its own reserved token has not been
    # renamed. Refuse rather than ship it — this is the licence gate.
    if reserved and reserved.lower() in family.lower() and family not in RENAME:
        raise SystemExit(
            f"{src.name}: declares Reserved Font Name {reserved!r} and family "
            f"{family!r} has no entry in RENAME. A subset is a Modified "
            "Version; OFL clause 3 forbids it from carrying the reserved name. Add "
            "a rename before vendoring this face."
        )

    font = TTFont(str(src))
    options = ftsubset.Options()
    options.layout_features = list(KEPT_FEATURES)
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.notdef_outline = True
    options.recalc_bounds = True
    options.drop_tables = []

    subsetter = ftsubset.Subsetter(options=options)
    subsetter.populate(unicodes=points)
    subsetter.subset(font)

    if family in RENAME:
        rename_family(font, family, RENAME[family])

    target = FONTS / f"{src.stem}-Latin.ttf"
    before = src.stat().st_size
    if write:
        font.save(str(target))
        after = target.stat().st_size
    else:
        with tempfile.NamedTemporaryFile(suffix=".ttf") as fh:
            font.save(fh.name)
            after = Path(fh.name).stat().st_size
    font.close()
    return target.name, before, after


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="report what would change; write nothing")
    args = ap.parse_args()

    sources = sorted(UPSTREAM.glob("*.ttf"))
    if not sources:
        print(f"no upstream faces in {UPSTREAM}", file=sys.stderr)
        return 2

    points = required_codepoints()
    print(f"glyph set: {len(points)} codepoints "
          f"(declared Latin base + every character the built page uses)")

    total_before = total_after = 0
    for src in sources:
        name, before, after = subset_one(src, points, write=not args.check)
        total_before += before
        total_after += after
        print(f"  {src.name:<32} {before:>8,} -> {after:>8,} B   ({name})")

    print(f"  {'TOTAL':<32} {total_before:>8,} -> {total_after:>8,} B "
          f"({100 * (1 - total_after / total_before):.0f}% smaller)")
    if args.check:
        print("--check: nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
