"""IMPRINT.md is a render, short, and names only what exists.

The imprint is the first page a newborn model reads (roadmap row `imprint`).
A hand edit, a reader that does not exist, a maintainer's address or a page
too long for a small model teaches the wrong estate — each is red here.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

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


def test_imprint_fits_the_char_cap() -> None:
    """A harness truncates by characters, not lines: past the cap the tail is never read."""
    for name, text in (("IMPRINT.md", _page()), ("render", gen.render())):
        assert len(text) <= gen.MAX_CHARS, f"{name} is {len(text)} chars, over {gen.MAX_CHARS}"


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


@pytest.mark.parametrize("page", ["IMPRINT.md", "IMPRINT.short.md"])
def test_no_maintainer_identity_or_private_domain(page: str) -> None:
    hits = [ln for ln in (REPO / page).read_text(encoding="utf-8").splitlines() if OPERATOR.search(ln) or re.search(r"pazny", ln, re.I)]
    assert not hits, "the imprint names the maintainer:\n" + "\n".join(hits)


def test_charter_is_claude_md_verbatim() -> None:
    claude = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    charter = claude.split("\n## Working in nOS\n", 1)[1].split("\n## ", 1)[0].strip("\n")
    section = _page().split("\n## 1. ", 1)[1].split("\n## ", 1)[0]
    assert section.split("\n", 2)[2].strip("\n") == charter


# 2026-10-10: a 15 kB imprint in an 8192 window evicted the user's message on qwen3:14b.
def _short() -> str:
    return (REPO / "IMPRINT.short.md").read_text(encoding="utf-8")


def test_short_imprint_is_the_render() -> None:
    assert _short() == gen.render_short(), "IMPRINT.short.md is hand-edited or stale — run tools/imprint-gen.py"


def test_short_imprint_fits_the_token_cap() -> None:
    """No tokenizer is installed: chars / CHARS_PER_TOKEN (3, below the ~4 of English prose) over-counts."""
    for name, text in (("IMPRINT.short.md", _short()), ("render", gen.render_short())):
        tokens = -(-len(text) // gen.CHARS_PER_TOKEN)
        assert tokens <= gen.SHORT_MAX_TOKENS, f"{name} is ~{tokens} tokens, over {gen.SHORT_MAX_TOKENS}"


def test_short_imprint_keeps_every_heading_of_the_full_one() -> None:
    heads = lambda t: re.findall(r"^## (.+)$", t, re.M)  # noqa: E731
    assert heads(_short()) == heads(_page()), "a section of IMPRINT.md was dropped from the short one"


def test_short_imprint_keeps_every_charter_law() -> None:
    section = _short().split("\n## 1. ", 1)[1].split("\n## ", 1)[0]
    laws = [" ".join(b.split()) for b in gen.charter_text().split("\n- ")[1:]]
    assert laws and all(gen.first_sentence(b) in section for b in laws), "a charter law is missing"


def test_check_sees_a_stale_short_imprint(tmp_path, monkeypatch) -> None:
    stale = tmp_path / "IMPRINT.short.md"
    stale.write_text("stale\n", encoding="utf-8")
    monkeypatch.setattr(gen, "SHORT_TARGET", stale)
    monkeypatch.setattr("sys.argv", ["imprint-gen.py", "--check"])
    assert gen.main() == 1, "--check passed with a stale IMPRINT.short.md"
