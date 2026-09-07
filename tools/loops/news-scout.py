#!/usr/bin/env python3
"""news-scout runner — fetch the loop's declared feeds, extract + dedup.

The step logic behind files/anatomy/loops/news-scout.loop.yml. THE MANIFEST is
the single source of the sources (and of the loop's shape, which
tools/loop-graph-gen.py draws); this runner reads the same file, so a feed added
to the manifest is fetched with no code change — the parametrisation the graph
shows is the parametrisation the runner executes.

  Phase 1 (this file): fetch → parse (RSS + Atom) → normalise → dedup → emit.
  Phase 2 (next): `--to-keap` consolidates the items into the KEAP corpus.

A scout that dies on one dead feed is useless, so a source that 404s, times out
or fails to parse is logged to stderr and SKIPPED — the run continues and the
exit code reflects "did we get anything", not "was every feed perfect".

    tools/loops/news-scout.py             # all feeds → JSON items on stdout
    tools/loops/news-scout.py --limit 5   # cap items per source
    tools/loops/news-scout.py --source hn # one source by manifest id

Exit: 0 got items · 1 every source failed (nothing to consolidate) · 2 bad usage.

ponytail: stdlib xml.etree parse of RSS/Atom, not feedparser — enough for the
declared feeds; reach for feedparser if a feed's dialect defeats it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import yaml

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MANIFEST = os.path.join(REPO, "files", "anatomy", "loops", "news-scout.loop.yml")
_UA = "nos-news-scout/1 (+https://thisisait.eu)"


def _sources() -> list[dict]:
    m = yaml.safe_load(open(MANIFEST, encoding="utf-8")) or {}
    return (m.get("params") or {}).get("sources") or []


def _local(tag: str) -> str:
    """Strip the XML namespace: `{http://www.w3.org/2005/Atom}entry` → `entry`."""
    return tag.rsplit("}", 1)[-1].lower()


def _text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


def _child(entry, name: str):
    for c in entry:
        if _local(c.tag) == name:
            return c
    return None


def _link_of(entry) -> str:
    """RSS <link>text</link> or Atom <link href="..."/> (prefer rel=alternate)."""
    best = ""
    for c in entry:
        if _local(c.tag) != "link":
            continue
        href = c.get("href")
        if href:
            if c.get("rel", "alternate") == "alternate":
                return href.strip()
            best = best or href.strip()
        elif c.text:
            return c.text.strip()
    return best


def _items(xml_bytes: bytes) -> list[ET.Element]:
    root = ET.fromstring(xml_bytes)
    return [e for e in root.iter() if _local(e.tag) in ("item", "entry")]


def fetch(source: dict, limit: int, log) -> list[dict]:
    url = source.get("url", "")
    sid = source.get("id", "?")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})  # noqa: S310 — declared feed
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            raw = resp.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        log(f"  [skip] {sid}: fetch failed ({type(exc).__name__}: {exc})")
        return []
    try:
        entries = _items(raw)
    except ET.ParseError as exc:
        log(f"  [skip] {sid}: not parseable XML ({exc})")
        return []

    out = []
    for e in entries:
        title = _text(_child(e, "title"))
        link = _link_of(e)
        if not (title and link):
            continue
        date = (_text(_child(e, "pubdate")) or _text(_child(e, "published"))
                or _text(_child(e, "updated")))
        summary = _text(_child(e, "description")) or _text(_child(e, "summary"))
        out.append({"source": sid, "source_label": source.get("label", sid),
                    "title": title, "link": link, "published": date,
                    "summary": summary[:500]})
        if limit and len(out) >= limit:
            break
    log(f"  [ok]   {sid}: {len(out)} item(s)")
    return out


def dedup(items: list[dict]) -> list[dict]:
    """One row per link (canonical id); a title repeated across feeds also
    collapses. First occurrence wins — sources are listed in priority order."""
    seen: set[str] = set()
    out = []
    for it in items:
        key = it["link"].split("#")[0].rstrip("/") or it["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def run(limit: int, only: str | None, log) -> list[dict]:
    sources = _sources()
    if only:
        sources = [s for s in sources if s.get("id") == only]
        if not sources:
            log(f"no source with id {only!r} in the manifest")
    raw: list[dict] = []
    for s in sources:
        raw.extend(fetch(s, limit, log))
    items = dedup(raw)
    log(f"  extract: {len(raw)} fetched → {len(items)} after dedup")
    return items


_TAG = re.compile(r"<[^>]+>")


def _inbox() -> str:
    """The keap-consolidate drop dir. It sweeps ~/keap/inbox and ships a .md's
    CONTENT as a capture (INLINE_TEXT_EXT), so we write there and reuse the whole
    intake — deterministic sid + upsert means a re-run overwrites, never dupes."""
    root = os.environ.get("KEAP_INBOX") or os.path.join(
        os.environ.get("KEAP_HOME") or os.path.join(os.path.expanduser("~"), "keap"), "inbox")
    return os.path.join(root, "news-scout")


def _as_markdown(it: dict) -> str:
    body = _TAG.sub("", it.get("summary", "")).strip()
    fm = {"title": it["title"], "source": it.get("source_label", it["source"]),
          "link": it["link"], "published": it.get("published", ""),
          "captured_by": "news-scout"}
    front = "\n".join(f'{k}: "{str(v)}"' for k, v in fm.items())
    return f"---\n{front}\n---\n\n# {it['title']}\n\n{body}\n\nSource: {it['link']}\n"


def to_keap(items: list[dict], log) -> int:
    """Drop each item as a deterministic .md into the inbox. Filename keys on the
    link so tonight's re-run overwrites the same file — idempotent by design."""
    out_dir = _inbox()
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for it in items:
        h = hashlib.sha1(it["link"].encode("utf-8")).hexdigest()[:12]  # noqa: S324 — filename key, not security
        path = os.path.join(out_dir, f"{it['source']}-{h}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_as_markdown(it))
        n += 1
    log(f"  consolidate: wrote {n} item(s) to {out_dir} "
        f"(keap-consolidate sweeps them into the corpus review queue)")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=0, help="max items per source (0 = all)")
    ap.add_argument("--source", metavar="ID", help="fetch only this manifest source id")
    ap.add_argument("--to-keap", action="store_true",
                    help="drop items as .md into the KEAP inbox instead of printing JSON")
    args = ap.parse_args()

    def log(line: str) -> None:
        print(line, file=sys.stderr, flush=True)

    log("news-scout: fetch + extract" + (" + consolidate → KEAP" if args.to_keap else ""))
    items = run(args.limit, args.source, log)
    if args.to_keap:
        to_keap(items, log)
    else:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0 if items else 1


if __name__ == "__main__":
    raise SystemExit(main())
