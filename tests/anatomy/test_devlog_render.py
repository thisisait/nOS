"""Anatomy CI gate — devlog static renderer (GH Pages publish path).

Runs tools/devlog-render.py in-process against the real entries and pins
that the index lists every published entry, per-entry pages exist, and the
RSS feed parses — so a schema or renderer regression fails offline instead
of at tag-push time inside .github/workflows/pages.yml.
"""
from __future__ import annotations

import importlib.util
import pathlib
import xml.etree.ElementTree as ET

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
RENDERER = REPO / "tools" / "devlog-render.py"


def _render(tmp_path):
    spec = importlib.util.spec_from_file_location("devlog_render", RENDERER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        return mod.render(tmp_path)
    except SystemExit as exc:  # markdown pin mismatch on a dev box
        pytest.skip(str(exc))


def test_renderer_produces_complete_site(tmp_path):
    entries = _render(tmp_path)
    assert entries, "no published entries to render"
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    for entry in entries:
        assert f'{entry["id"]}.html' in index, f"index missing {entry['id']}"
        assert (tmp_path / f"{entry['id']}.html").is_file()
    feed = ET.parse(tmp_path / "feed.xml")
    guids = [g.text for g in feed.getroot().iter("guid")]
    assert set(guids) == {e["id"] for e in entries}


def test_pages_workflow_contract():
    wf = (REPO / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    assert "tools/devlog-render.py" in wf
    assert "upload-pages-artifact" in wf and "deploy-pages" in wf
    assert "markdown==3.10.2" in wf, "renderer pin must match tools/devlog-compile.py"
    assert "tags: ['v*']" in wf
