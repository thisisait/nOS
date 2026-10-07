"""Anatomy gate — tools/body.py says what a level means in the lexicon's words.

WHY (repo-body-plan I-5, 2026-10-07). body.py carried its own one-line meaning
per level; four of them contradicted state/genome/lexicon.yml and IMPRINT.md §3
rendered the wrong ones to every newborn model. The lexicon is the one source
(ssot/doctrine/body-plan.md §1); body.py may only repeat it.

Reads what body.py prints for `tools/body.py <level>`, not its source.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _body():
    spec = importlib.util.spec_from_file_location("body", REPO / "tools" / "body.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _printed_gloss(body, level: str) -> str:
    """The text between `<level> — ` and the trailing `: <count>`."""
    out, argv = io.StringIO(), sys.argv
    sys.argv = ["body.py", level]
    try:
        with contextlib.redirect_stdout(out):
            body.main()
    finally:
        sys.argv = argv
    first = out.getvalue().splitlines()[0]
    return first.split(" — ", 1)[1].rsplit(": ", 1)[0]


def test_every_level_gloss_is_the_lexicon_meaning():
    words = yaml.safe_load((REPO / "state/genome/lexicon.yml").read_text(encoding="utf-8"))["words"]
    body = _body()
    bad = []
    for level in body.LEVELS:
        want = " ".join(str(words[level]["means"]).split())
        got = _printed_gloss(body, level)
        if got != want:
            bad.append(f"{level}: body.py says {got!r}, lexicon says {want!r}")
    assert not bad, "\n".join(bad)
