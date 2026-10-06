"""IMPRINT.md is a render, short, and names only what exists.

The imprint is the first page a newborn model reads (roadmap row `imprint`).
A hand edit, a reader that does not exist, a maintainer's address or a page
too long for a small model teaches the wrong estate — each is red here.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re

from test_templates_name_no_operator import OPERATOR

REPO = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("imprint_gen", REPO / "tools" / "imprint-gen.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def _page() -> str:
    return (REPO / "IMPRINT.md").read_text(encoding="utf-8")


def test_imprint_is_the_render() -> None:
    assert _page() == gen.render(), "IMPRINT.md is hand-edited or stale — run tools/imprint-gen.py"


def test_imprint_fits_the_cap() -> None:
    for name, text in (("IMPRINT.md", _page()), ("render", gen.render())):
        assert text.count("\n") <= gen.MAX_LINES, f"{name} is over {gen.MAX_LINES} lines"


def test_every_section_is_present_in_order() -> None:
    heads = re.findall(r"^## (.+)$", _page(), re.M)
    assert heads == [t for t, _ in gen.SECTIONS] + ["Sources"]


def test_every_reader_named_exists_and_is_listed() -> None:
    section = _page().split("## 4. ", 1)[1].split("\n## ", 1)[0]
    named = re.findall(r"^- `tools/([^`]+)`", section, re.M)
    readers = (REPO / "tools/README.md").read_text(encoding="utf-8")
    readers = readers.split("\n## Readers", 1)[1].split("\n## ", 1)[0]
    assert named and named[0] == "red-status.py"
    for n in named:
        assert (REPO / "tools" / n).is_file(), f"{n} does not exist"
        assert f"- `{n}` —" in readers, f"{n} is not in tools/README.md §Readers"


def test_no_maintainer_identity_or_private_domain() -> None:
    hits = [ln for ln in _page().splitlines() if OPERATOR.search(ln) or re.search(r"pazny", ln, re.I)]
    assert not hits, "the imprint names the maintainer:\n" + "\n".join(hits)


def test_charter_is_claude_md_verbatim() -> None:
    claude = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    charter = claude.split("\n## Working in nOS\n", 1)[1].split("\n## ", 1)[0].strip("\n")
    section = _page().split("\n## 1. ", 1)[1].split("\n## ", 1)[0]
    assert section.split("\n", 2)[2].strip("\n") == charter
