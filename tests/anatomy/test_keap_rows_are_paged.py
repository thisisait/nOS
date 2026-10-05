"""Anatomy CI gate — a KEAP table is read to its last page.

/rows caps a page at 500 and hands back `nextCursor`. On 2026-10-03 the roadmap
held 508 rows; every reader saw 500 and roadmap-seed would have re-inserted the
other eight. keap_api.paged() walks the cursor; no tool may stop at page one.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
from keap_api import paged  # noqa: E402


def test_paged_follows_the_cursor_to_the_end():
    pages = {None: ([1, 2], "2"), "2": ([3, 4], "4"), "4": ([5], None)}

    def fetch(url):
        cur = re.search(r"cursor=([^&]+)", url)
        rows, nxt = pages[cur.group(1) if cur else None]
        return {"success": True, "data": {"rows": rows, "nextCursor": nxt}}

    out = paged(fetch, "http://keap/api/tables/t/rows")
    assert out["data"]["rows"] == [1, 2, 3, 4, 5]
    assert "nextCursor" not in out["data"]


def test_no_tool_reads_a_table_as_one_page():
    bad = []
    for p in (REPO / "tools").glob("*.py"):
        text = p.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            # a page-one read is fine only in a file that walks nextCursor itself
            if re.search(r"/rows\?limit=500", line) and "paged" not in line and "nextCursor" not in text:
                bad.append(f"{p.relative_to(REPO)}:{i}")
    assert not bad, f"read past page one with keap_api.paged(): {bad}"
