"""Devlog media pipeline — repo-hosted screenshots reach the live posts.

Doctrine (docs/devlog/README.md + docs/plans/devlog-screenshots.md): the repo is
the source of truth, the WordPress media library is disposable presentation, and
the operator's contract is "overwrite the file, keep the name, re-run the
playbook, the live post shows the new picture".

Three things have to hold for that contract, and each has a failure mode that is
silent rather than loud:

  1. A referenced image that does not exist must FAIL the compile — otherwise the
     post publishes with a broken image and nothing complains.
  2. The image's sha256 must ride in the bundle AND fold into the entry's content
     hash — otherwise replacing the bytes re-uploads the image (new URL) while
     every post keeps pointing at the deleted one.
  3. The syntax must be documentable — a post explaining ![](../media/x.png) in
     backticks must not be read as a real reference (this gate exists because
     that is exactly what happened while writing the first such post).

Offline: pure compile-level checks against a temp entry tree. No WP, no network.
"""

from __future__ import annotations

import hashlib
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "docs" / "devlog" / "nos-core" / "media"

_spec = importlib.util.spec_from_file_location("devlog_compile", ROOT / "tools" / "devlog-compile.py")
compile_mod = importlib.util.module_from_spec(_spec)
sys.modules["devlog_compile"] = compile_mod
_spec.loader.exec_module(compile_mod)

FRONTMATTER = """---
id: {eid}
title: "Fixture"
date: 2026-07-20
namespace: nos-core
summary: "fixture entry"
---
{body}
"""

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6360000002000100ff ff03000006"
    "00057b0d0a2d0000000049454e44ae426082".replace(" ", "")
)


def _tree(tmp_path: pathlib.Path, body: str, *, media: dict[str, bytes] | None = None):
    year = tmp_path / "2026"
    year.mkdir(parents=True)
    (year / "2026-07-20-fixture.md").write_text(
        FRONTMATTER.format(eid="2026-07-20-fixture", body=body), encoding="utf-8"
    )
    md = tmp_path / "media"
    md.mkdir()
    for name, payload in (media or {}).items():
        (md / name).write_bytes(payload)
    return tmp_path


def test_missing_media_fails_the_compile(tmp_path):
    """A referenced-but-absent image is a hard error, not a broken live post."""
    tree = _tree(tmp_path, "![shot](../media/nope.png)\n")
    with pytest.raises(ValueError, match="not found"):
        compile_mod.load_entries(tree)


def test_media_hash_lands_in_the_entry(tmp_path):
    tree = _tree(tmp_path, "![a shot](../media/ok.png)\n", media={"ok.png": PNG_BYTES})
    entry = compile_mod.load_entries(tree)[0]
    assert entry["media"] == [
        {
            "filename": "ok.png",
            "alt": "a shot",
            "sha256": hashlib.sha256(PNG_BYTES).hexdigest(),
        }
    ]


def test_replacing_bytes_changes_the_content_hash(tmp_path):
    """Same markdown, new image bytes → the post must still be marked dirty.

    Without this the sync uploads the replacement (minting a new URL) and then
    finds every post 'unchanged', so no post ever references the new image.
    """
    body = "![a shot](../media/ok.png)\n"
    first = compile_mod.compile_bundle(_tree(tmp_path / "a", body, media={"ok.png": PNG_BYTES}))
    second = compile_mod.compile_bundle(
        _tree(tmp_path / "b", body, media={"ok.png": PNG_BYTES + b"\x00"})
    )
    assert first != second, "media bytes must participate in the entry content hash"


def test_media_syntax_inside_code_is_not_a_reference(tmp_path):
    """A post may document the syntax; backticked examples resolve to nothing."""
    body = "Reference images as `![alt](../media/x.png)` in the body.\n"
    entry = compile_mod.load_entries(_tree(tmp_path, body))[0]
    assert "media" not in entry


def test_committed_media_is_referenced_by_some_entry():
    """No orphan screenshots — every committed image is used, or it is dead weight."""
    if not MEDIA_DIR.is_dir():
        pytest.skip("no media directory yet")
    committed = {p.name for p in MEDIA_DIR.iterdir() if p.is_file() and not p.name.startswith(".")}
    referenced = {
        item["filename"]
        for entry in compile_mod.load_entries()
        for item in entry.get("media", [])
    }
    assert not (committed - referenced), (
        "committed screenshots referenced by no entry (delete them or use them): "
        f"{sorted(committed - referenced)}"
    )
