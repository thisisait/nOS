"""Per-row roadmap seeds: the format parses, and the PUBLIC repo carries no rows.

dtt-seed-per-row-file (docs/plans/datatables-subsystem.md §6): a roadmap row is
one markdown+frontmatter file in a PRIVATE seed repo (NOS_SEED_DIR). nOS is
public, so two things must hold and are gated here:

1. The format works — the template and a round-tripped file parse into the row
   shape roadmap-seed.py consumes.
2. THE PRIVACY INVARIANT — tools/roadmap-seed.py (the public loader) inlines NO
   row content. The whole point of the migration is that ideas leave the public
   repo; a monolith creeping back (a `row(...)` wall, an inline `R.append(dict`)
   would republish them. The loader must READ files, not carry them.
"""

from __future__ import annotations

import os
import sys

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import roadmap_seed_lib as lib  # noqa: E402

_TEMPLATE = os.path.join(_REPO, "state", "roadmap", "_template.md")
_SEEDER = os.path.join(_REPO, "tools", "roadmap-seed.py")


def test_template_parses():
    row = lib.parse_file(_TEMPLATE)
    for k in ("slug", "title", "track", "status"):
        assert row.get(k), f"_template.md parsed with empty {k}"
    # status drives which date column is set — exactly one, never both.
    assert ("target" in row) ^ ("occurred_at" in row), \
        "exactly one of target/occurred_at must be set"


def test_round_trip(tmp_path):
    f = tmp_path / "sample-row.md"
    f.write_text(
        "---\n"
        "slug: sample-row\n"
        "title: A sample row\n"
        "parent: sec\n"
        "track: security\n"
        "status: shipped\n"
        "when: 2026-08-03\n"
        'refs: "a · b"\n'
        "---\n"
        "The body prose.\n",
        encoding="utf-8",
    )
    row = lib.parse_file(str(f))
    assert row["slug"] == "sample-row"
    assert row["parent"] == "sec"
    assert row["body"] == "The body prose."
    # shipped -> occurred_at, not target.
    assert "occurred_at" in row and "target" not in row
    # load_rows skips _-prefixed and reads the sample.
    (tmp_path / "_template.md").write_text(_TEMPLATE_MIN, encoding="utf-8")
    rows = lib.load_rows(str(tmp_path))
    assert [r["slug"] for r in rows] == ["sample-row"], "load_rows must skip _-files"


def test_identity_fields_are_required(tmp_path):
    # slug and title are the only hard requirements; status/when are optional
    # (the live table holds rows with neither, and extraction must be lossless).
    no_slug = tmp_path / "a.md"
    no_slug.write_text("---\ntitle: has no slug\n---\nbody\n", encoding="utf-8")
    with pytest.raises(ValueError):
        lib.parse_file(str(no_slug))
    no_title = tmp_path / "b.md"
    no_title.write_text("---\nslug: b\n---\nbody\n", encoding="utf-8")
    with pytest.raises(ValueError):
        lib.parse_file(str(no_title))


def test_status_and_when_are_optional(tmp_path):
    f = tmp_path / "dateless.md"
    f.write_text("---\nslug: dateless\ntitle: a row with no date or status\n---\nx\n",
                 encoding="utf-8")
    row = lib.parse_file(str(f))
    assert row["slug"] == "dateless"
    assert "status" not in row and "target" not in row and "occurred_at" not in row


def test_public_loader_carries_no_row_content():
    """The privacy invariant: roadmap-seed.py reads files, it does not inline rows."""
    src = open(_SEEDER, encoding="utf-8").read()
    assert "load_rows(seed_dir())" in src, \
        "roadmap-seed.py must load rows from the private seed dir"
    # A monolith would show as many row(...) calls or an inline R.append(dict(...).
    assert "R.append(dict(" not in src, \
        "roadmap-seed.py inlines rows again — the private content is back in public"
    n_rowcalls = src.count("\nrow(")
    assert n_rowcalls == 0, \
        f"roadmap-seed.py has {n_rowcalls} inline row() calls — content must live in NOS_SEED_DIR"
    # Belt-and-braces: the file is machinery, not a 2000-line seed dump.
    assert len(src.splitlines()) < 260, \
        "roadmap-seed.py grew back toward a monolith — rows belong in the private repo"


_TEMPLATE_MIN = (
    "---\nslug: _t\ntitle: t\ntrack: platform\nstatus: next\nwhen: 2026-09-05\n---\nx\n"
)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
