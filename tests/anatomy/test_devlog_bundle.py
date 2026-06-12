"""Anatomy CI gate — devlog nos-core entries + bundle freshness.

Pins (doctrine: docs/devlog/README.md):
  - every docs/devlog/nos-core/**/*.md validates the frontmatter schema
    (required fields, id == filename stem, unique ids, ISO date, year-dir
    placement, lowercase-dash tags) — tools/devlog-compile.py is the
    validator, imported in-process;
  - the committed state/devlog-bundle.jsonl is byte-identical to an
    in-process recompile (lockfile-sync precedent — a stale bundle would
    make tasks/devlog-sync.yml publish outdated content);
  - the bundle parses as JSONL, is sorted by id, and every line carries the
    sync contract fields (slug, content_hash, body_html, status != draft).
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
COMPILER = REPO / "tools" / "devlog-compile.py"
BUNDLE = REPO / "state" / "devlog-bundle.jsonl"

SYNC_FIELDS = {"id", "slug", "namespace", "title", "date", "status", "summary",
               "tags", "body_md", "body_html", "content_hash"}


def _compiler():
    spec = importlib.util.spec_from_file_location("devlog_compile", COMPILER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_entries_validate():
    mod = _compiler()
    entries = mod.load_entries()  # raises ValueError with the violation list
    assert entries, "no devlog entries found under docs/devlog/nos-core/"


def test_bundle_is_fresh():
    mod = _compiler()
    try:
        recompiled = mod.compile_bundle()
    except SystemExit as exc:  # markdown version pin mismatch
        pytest.skip(str(exc))
    assert BUNDLE.exists(), "state/devlog-bundle.jsonl missing — run tools/devlog-compile.py"
    assert BUNDLE.read_text(encoding="utf-8") == recompiled, (
        "state/devlog-bundle.jsonl is STALE — run tools/devlog-compile.py and commit"
    )


def test_bundle_shape():
    lines = [json.loads(l) for l in BUNDLE.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines, "bundle is empty"
    ids = [e["id"] for e in lines]
    assert ids == sorted(ids), "bundle must be sorted by id (determinism)"
    for entry in lines:
        missing = SYNC_FIELDS - set(entry)
        assert not missing, f"{entry.get('id')}: bundle line missing {missing}"
        assert entry["status"] != "draft", f"{entry['id']}: drafts must not reach the bundle"
        assert entry["namespace"] == "nos-core"
