"""Face BFF must filter book-scoped tables server-side (finding 1).

RETRO-RED: BooksApp filtered book_owner in the browser only; a second manager
GET /bff/tables?slug=invoice still received every client's rows.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
BFF = REPO / "files/anatomy/face/src/routes/bff/tables/+server.ts"
SCOPE = REPO / "files/anatomy/face/src/lib/security/bookScope.ts"


def test_readable_summaries_still_has_a_function_header():
    """iiab compose-up died on Unexpected ']': scopeContext's `}` ate the
    `function readableSummaries(` line. Pytest never runs vite; this pin does."""
    src = BFF.read_text(encoding="utf-8")
    assert "function readableSummaries(" in src
    src = BFF.read_text(encoding="utf-8")
    assert "filterBookRows" in src
    assert "mayWriteBookRow" in src
    assert "BOOK_SCOPED" in src
    # Filter before decorate — otherwise a manager still receives every row
    # and only the display labels are scoped.
    assert src.find("filterBookRows") < src.find("decorateRowRefs")
    assert SCOPE.is_file()
    scope = SCOPE.read_text(encoding="utf-8")
    assert "assignedBookOwners" in scope
    assert "canViewAnatomy" in scope


def test_offboard_delete_uses_the_human_door():
    api = (REPO / "tools/keap_api.py").read_text(encoding="utf-8")
    assert "def delete_row" in api
    assert 'method="DELETE"' in api or "method='DELETE'" in api
    off = (REPO / "tools/offboard-book-owner.py").read_text(encoding="utf-8")
    assert "execute_keap" in off
    assert "keap_api.delete_row" in off
