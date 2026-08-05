"""The face has a shared vocabulary for in-window furniture. Keep it shared.

WHAT WAS MEASURED, 2026-08-05, when asked whether the shell had reusable
components at all. The DESKTOP layer was well factored — Window, Dock,
SnapOverlay, TileDivider, CommandPalette, NativeHost, ServiceFrame all exist
once and are used everywhere. Everything INSIDE a window was not:

  * `.card` existed three times with TWO meanings. KeapExploreApp's and
    ServiceFrame's rules were BYTE-IDENTICAL (margin:auto, text-align:center,
    max-width:420px, flex column, gap:10px, padding:24px) — a literal
    copy-paste — while BoneView's `.card` was a translucent content box. One
    word, two things, neither safely changeable.
  * two components rolled their own tab strip and NEITHER was a tablist: one
    used `aria-current="page"` (the attribute for navigation links, which says
    nothing about a selected tab), the other had no ARIA at all. Reaching the
    third view took three Tab presses instead of one arrow key.
  * icons were derived three different ways, and one of them was WRONG:
    `Dock.svelte` rendered `app.icon.slice(0, 2)`, and `.slice()` counts UTF-16
    code units. Verified in node: `"⚡🔥".slice(0,2)` → `"⚡\\ud83d"`, a lone
    surrogate, which renders as `⚡�`. Reachable, because hub icons come from an
    operator-authored `hub_card` glyph the BFF passes through untouched.

These checks pin the STRUCTURE — that the shared components exist and are the
ones being used. Their behaviour is pinned where it can actually be executed:
`glyph.test.ts` and `tone.test.ts` in vitest.

Retro-red: verified by restoring `.slice(0, 2)` in Dock.svelte (red on the
grapheme check) and by re-adding a local `.card` rule to BoneView (red on the
panel check).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FACE = REPO / "files/anatomy/face/src"
UI = FACE / "lib/components/ui"

# Every .svelte under the app tree, excluding the primitives themselves — they
# are allowed, indeed required, to contain the rules everyone else must not.
def _consumers() -> list[Path]:
    return sorted(p for p in FACE.rglob("*.svelte") if UI not in p.parents)


_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)


def _code(path: Path) -> str:
    """Source with comments stripped.

    Necessary, not fastidious. The first version of the icon check below fired
    on `Dock.svelte` — because the comment explaining the fix quotes the broken
    call it replaced. A gate that cannot tell a description of a defect from
    the defect will flag every well-documented repair, which is a fast way to
    teach people to stop documenting repairs. Fourth substring false positive
    of the day; the pattern is always the same.
    """
    src = path.read_text(encoding="utf-8")
    src = _HTML_COMMENT.sub("", src)
    src = _BLOCK_COMMENT.sub("", src)
    return _LINE_COMMENT.sub("", src)


def test_the_primitives_exist():
    """Positive control — without these the checks below are vacuous."""
    for name in ("Panel.svelte", "Tabs.svelte", "Icon.svelte", "StatusNote.svelte"):
        assert (UI / name).is_file(), f"$lib/components/ui/{name} is gone"


# ── Icons ───────────────────────────────────────────────────────────────────

_CODE_UNIT_CUT = re.compile(r"\bicon\s*\.\s*(slice|substring|substr)\s*\(")


@pytest.mark.parametrize("path", _consumers(), ids=lambda p: p.stem)
def test_no_component_cuts_an_icon_by_code_unit(path):
    hit = _CODE_UNIT_CUT.search(_code(path))
    assert not hit, (
        f"{path.name} truncates an icon with .{hit.group(1)}(), which counts "
        f"UTF-16 code units and can cut a surrogate pair in half — the Dock did "
        f"exactly this and rendered '⚡🔥' as '⚡\\ufffd'. Use <Icon> or "
        f"clampGlyphs(), which count graphemes."
    )


# ── Tabs ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", _consumers(), ids=lambda p: p.stem)
def test_no_component_rolls_its_own_tab_strip(path):
    """A tab strip is an ARIA pattern, not a row of buttons.

    Keyed on `role="tab"` rather than on a `.tabs` class: the class name is
    cosmetic, and a component that gets the ROLE right while hand-rolling the
    roving tabindex is still reimplementing the pattern. Both of the two
    pre-existing strips lacked the role entirely, which is the worse failure —
    so the check that catches them is the one below, on the class.
    """
    src = _code(path)
    if 'role="tab"' in src or "role='tab'" in src:
        pytest.fail(
            f"{path.name} declares role=\"tab\" outside $lib/components/ui. Use "
            f"<Tabs>, which implements the full pattern — roving tabindex, "
            f"arrow keys, Home/End, aria-selected. A partial implementation is "
            f"how both earlier strips ended up keyboard-hostile."
        )


@pytest.mark.parametrize("path", _consumers(), ids=lambda p: p.stem)
def test_no_component_styles_a_private_tab_strip(path):
    src = _code(path)
    assert not re.search(r"^\s*\.tabs?\s*\{", src, re.MULTILINE), (
        f"{path.name} styles its own `.tab`/`.tabs`. That is how the shell "
        f"ended up with two tab strips that looked alike and behaved "
        f"differently — one of them announcing itself to assistive tech as a "
        f"set of navigation links."
    )


# ── Panels ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", _consumers(), ids=lambda p: p.stem)
def test_no_component_defines_a_private_card(path):
    """`.card` is the word that meant two things. It now means <Panel>.

    Deliberately narrow: this forbids the CLASS DEFINITION, not the word. A
    component may still have `.cards` (a grid of them) or mention cards in a
    comment — those are layout and prose, and a gate that fired on them would
    be noise.
    """
    src = _code(path)
    assert not re.search(r"^\s*\.card\s*[{,]", src, re.MULTILINE), (
        f"{path.name} defines a private `.card` rule. Two of these were "
        f"byte-identical copy-paste and a third meant something else entirely. "
        f"Use <Panel variant=\"content\"> for a surface holding data, or "
        f"<Panel variant=\"message\"> for a centred block that tells the "
        f"operator something."
    )


# ── The bar on the shared layer ─────────────────────────────────────────────


def test_the_primitives_layer_stays_a_vocabulary_not_a_library():
    components = sorted(p.name for p in UI.glob("*.svelte"))
    assert components, "no primitives at all — this gate is checking an empty directory"
    assert len(components) <= 8, (
        f"the primitives layer has grown to {len(components)} components "
        f"({components}). index.ts's bar is three divergent copies before "
        f"something is extracted; past eight this is a component library, which "
        f"is a different and much larger commitment."
    )
