"""tools/kiwix-status.py names the newer ZIM of each local book, or says UNKNOWN.

WHY. 11-01 the mini restored 335 ZIMs from a months-old backup and nothing in
nOS noticed they were stale. The reader compares each local file to the newest
dated file of the same book in the Kiwix OPDS catalog. A catalog it cannot read
must be UNKNOWN, never "current" — an empty answer would read as green.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

TOOL = pathlib.Path(__file__).resolve().parents[2] / "tools/kiwix-status.py"

CATALOG = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="https://specs.opds.io/opds-1.2">
  <entry><name>devdocs_en_python</name><flavour></flavour>
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim"
      href="https://download.kiwix.org/zim/devdocs/devdocs_en_python_2026-01.zim.meta4"/></entry>
  <entry><name>devdocs_en_python</name><flavour></flavour>
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim"
      href="https://download.kiwix.org/zim/devdocs/devdocs_en_python_2026-09.zim.meta4"/></entry>
  <entry><name>devdocs_en_rust</name><flavour></flavour>
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim"
      href="https://download.kiwix.org/zim/devdocs/devdocs_en_rust_2026-03.zim.meta4"/></entry>
</feed>
"""


def _run(tmp_path: pathlib.Path, catalog: str) -> dict:
    lib = tmp_path / "data"
    lib.mkdir()
    for name in ("devdocs_en_python_2026-01.zim", "devdocs_en_rust_2026-03.zim",
                 "devdocs_en_gone_2025-05.zim"):
        (lib / name).write_bytes(b"")
    p = subprocess.run([sys.executable, str(TOOL), "--dir", str(lib), "--catalog", catalog, "--json"],
                       capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    return {b["file"]: b for b in json.loads(p.stdout)["books"]}


def test_a_newer_file_is_named_with_its_age(tmp_path: pathlib.Path) -> None:
    cat = tmp_path / "catalog.xml"
    cat.write_text(CATALOG, encoding="utf-8")
    books = _run(tmp_path, str(cat))
    py = books["devdocs_en_python_2026-01.zim"]
    assert (py["status"], py["months_behind"], py["newest"]) == \
        ("behind", 8, "devdocs_en_python_2026-09.zim")
    assert books["devdocs_en_rust_2026-03.zim"]["status"] == "current"
    assert books["devdocs_en_gone_2025-05.zim"]["status"] == "gone"


def test_an_unreadable_catalog_is_unknown_never_current(tmp_path: pathlib.Path) -> None:
    books = _run(tmp_path, str(tmp_path / "no-such-catalog.xml"))
    assert {b["status"] for b in books.values()} == {"UNKNOWN"}
