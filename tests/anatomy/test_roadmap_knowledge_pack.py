"""roadmap-status --knowledge: the roadmap as ONE markdown file to attach to a
cloud conversation. Status comes from the live table (the seed files only seed
it), settled rows stay out unless asked, and every row's body survives whole."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from roadmap_seed_lib import knowledge_pack  # noqa: E402

ROWS = [
    {"slug": "iris-v3", "title": "Iris v3", "status": "active", "track": "iris",
     "parent": "", "refs": "serve.rs", "body": "Dates as days.\n\nSecond paragraph."},
    {"slug": "old", "title": "Old work", "status": "shipped", "track": "core", "body": "done"},
    {"slug": "idea", "title": "An idea", "status": "queued", "track": "", "parent": "iris-v3", "body": ""},
]


def test_a_pack_carries_live_status_and_whole_bodies_and_leaves_settled_out():
    md = knowledge_pack(ROWS, "nOS Roadmap", "2026-10-15")
    assert md.startswith("# nOS Roadmap") and "2026-10-15" in md.splitlines()[2]
    assert md.index("## active") < md.index("## queued"), "board order, not file order"
    assert "### iris-v3 — Iris v3" in md and "Dates as days.\n\nSecond paragraph." in md
    assert "parent: iris-v3" in md and "refs: serve.rs" in md
    assert "Old work" not in md and "+1 shipped/dropped" in md


def test_all_includes_the_settled_rows():
    md = knowledge_pack(ROWS, "nOS Roadmap", "2026-10-15", settled=True)
    assert "## shipped" in md and "### old — Old work" in md and "shipped/dropped" not in md
