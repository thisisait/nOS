"""A degraded invoice render carries the SAME data — only worse.

The pipeline-exercise loop (dtt `pipeline-exercise-loop-prompt`) feeds the
vision path crumpled, stained, low-resolution documents and scores the
extraction against the text the image was RENDERED from. That only works if two
things hold, and both are easy to break by accident:

  * the degradation is DETERMINISTIC in (doc id, profiles, seed) — otherwise a
    failing cycle cannot be re-rendered from its record, and the report is an
    anecdote;
  * a profile changes how the document is carried, never what it says — a
    generator that nudged an amount would make the oracle score a different
    document.

The second cannot be proven here without OCR, so this pins what it can: the
geometry survives, the page is not wiped, and the pixels actually changed (a
no-op "degradation" would pass a naive test while measuring nothing).
"""
import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = REPO / "state" / "fixtures" / "consulting-firm"
PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")

sys.path.insert(0, str(REPO / "tools"))
_spec = importlib.util.spec_from_file_location("gen_invoice_images",
                                               REPO / "tools" / "gen-invoice-images.py")
GEN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GEN)
from invoice_fixture import parse_image_txt  # noqa: E402


def _clean():
    rec = parse_image_txt((FIXTURE / "beta-002.image.txt").read_text(encoding="utf-8"))
    fonts = GEN.resolve_fonts() or [("default", "", "")]
    return rec, GEN.render(rec, fonts, 150)


def _bytes(img):
    return img.tobytes()


def test_same_seed_renders_the_same_bytes():
    rec, clean = _clean()
    a = GEN.degrade(clean.copy(), ["combo"], rec["id"], 7)
    b = GEN.degrade(clean.copy(), ["combo"], rec["id"], 7)
    assert _bytes(a) == _bytes(b)


def test_a_different_seed_renders_differently():
    rec, clean = _clean()
    a = GEN.degrade(clean.copy(), ["combo"], rec["id"], 7)
    b = GEN.degrade(clean.copy(), ["combo"], rec["id"], 8)
    assert _bytes(a) != _bytes(b)


@pytest.mark.parametrize("profile", [p for p in GEN.DEGRADE_PROFILES if p != "clean"])
def test_every_profile_marks_the_page_without_erasing_it(profile):
    rec, clean = _clean()
    out = GEN.degrade(clean.copy(), [profile], rec["id"], 3)
    assert out.size == clean.size, f"{profile} changed the page geometry"
    assert _bytes(out) != _bytes(clean), f"{profile} is a no-op"
    grey = out.convert("L")
    dark = sum(grey.histogram()[:128])
    assert dark > 200, f"{profile} wiped the document (only {dark} dark pixels left)"


def test_clean_is_the_control():
    rec, clean = _clean()
    assert _bytes(GEN.degrade(clean.copy(), ["clean"], rec["id"], 3)) == _bytes(clean)


def test_an_unknown_profile_is_refused():
    rec, clean = _clean()
    with pytest.raises(ValueError):
        GEN.degrade(clean, ["coffee-spill"], rec["id"], 1)
