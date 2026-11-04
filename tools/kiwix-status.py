#!/usr/bin/env python3
"""Is each ZIM in the Kiwix library the newest one the Kiwix catalog offers?

Per local `<book>_<YYYY-MM>.zim`: the newest dated file of the same book in the
OPDS catalog (library.kiwix.org), reported as current, behind N months, or gone
(no longer in the catalog). A file without a date is `undated`. A catalog it
cannot read makes every book UNKNOWN, never current. Downloads nothing.

Reads only. Exit 0 always.

Usage:
    tools/kiwix-status.py                      # library under {nos_data_root}/tenants/*/shared/kiwix/data
    tools/kiwix-status.py --dir DIR --catalog URL|FILE --json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

CATALOG = "https://library.kiwix.org/catalog/v2/entries?count=-1"
DATED = re.compile(r"^(?P<book>.+)_(?P<y>\d{4})-(?P<m>\d{2})\.zim$")


def _default_dirs() -> list[pathlib.Path]:
    """kiwix_data_dir is {nos_data_root}/tenants/<slug>/shared/kiwix/data; config.yml moves the root."""
    spec = importlib.util.spec_from_file_location("snapshot_status", pathlib.Path(__file__).with_name("snapshot-status.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    root = mod.data_root()
    return sorted(root.glob("tenants/*/shared/kiwix/data")) if root else []


def _read_catalog(src: str) -> bytes:
    if re.match(r"^https?://", src):
        with urllib.request.urlopen(src, timeout=60) as r:  # noqa: S310 — fixed public catalog or operator's URL
            return r.read()
    return pathlib.Path(src).read_bytes()


def newest_by_book(xml: bytes) -> dict[str, tuple[int, int, str]]:
    """book -> (year, month, filename) of its newest dated file in the catalog."""
    out: dict[str, tuple[int, int, str]] = {}
    for el in ET.fromstring(xml).iter():
        href = el.get("href", "") if el.tag.rsplit("}", 1)[-1] == "link" else ""
        name = href.rsplit("/", 1)[-1].removesuffix(".meta4")
        m = DATED.match(name)
        if m:
            cand = (int(m["y"]), int(m["m"]), name)
            out[m["book"]] = max(out.get(m["book"], cand), cand)
    return out


def collect(dirs: list[pathlib.Path], catalog: str) -> dict:
    report: dict = {"sources_missing": [], "catalog": catalog, "dirs": [str(d) for d in dirs], "books": []}
    files: list[pathlib.Path] = []
    for d in dirs:
        if not d.is_dir():  # glob on a missing dir (unmounted SSD) returns [], not an error
            report["sources_missing"].append(f"{d} (not a directory)")
            continue
        try:
            files += sorted(d.glob("*.zim"))
        except OSError as exc:
            report["sources_missing"].append(f"{d} ({exc.strerror or exc})")
    if not dirs:
        report["sources_missing"].append("no kiwix library dir ({nos_data_root}/tenants/*/shared/kiwix/data); pass --dir")
    try:
        newest = newest_by_book(_read_catalog(catalog))
    except (OSError, ET.ParseError, ValueError) as exc:
        report["sources_missing"].append(f"catalog {catalog} ({exc})")
        newest = None
    if newest == {}:  # a feed with no dated links (empty, paged, new shape) must not say every book is gone
        report["sources_missing"].append(f"catalog {catalog} (no dated ZIM links)")
        newest = None
    for f in files:
        row: dict = {"file": f.name, "dir": str(f.parent), "newest": None, "months_behind": None}
        m = DATED.match(f.name)
        if newest is None:
            row["status"] = "UNKNOWN"
        elif not m:
            row["status"] = "undated"
        elif m["book"] not in newest:
            row["status"] = "gone"
        else:
            y, mo, name = newest[m["book"]]
            behind = (y - int(m["y"])) * 12 + mo - int(m["m"])
            row.update(newest=name, months_behind=max(behind, 0),
                       status="behind" if behind > 0 else "current")
        report["books"].append(row)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", type=pathlib.Path, help="library dir (repeatable)")
    ap.add_argument("--catalog", default=CATALOG, help="OPDS catalog URL or file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = collect(args.dir or _default_dirs(), args.catalog)
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    for m in report["sources_missing"]:
        print(f"kiwix: UNKNOWN — {m} unreadable, not current")
    rows = sorted(report["books"], key=lambda b: (b["status"] != "behind", -(b["months_behind"] or 0), b["file"]))
    for b in rows:
        extra = f"  behind {b['months_behind']} months → {b['newest']}" if b["status"] == "behind" else ""
        print(f"  {b['status']:<8} {b['file']}{extra}")
    counts: dict[str, int] = {}
    for b in rows:
        counts[b["status"]] = counts.get(b["status"], 0) + 1
    print("kiwix: " + (", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "no ZIMs"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
