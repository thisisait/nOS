#!/usr/bin/env python3
"""devlog-render — static site generator for the nos-core devlog.

Renders docs/devlog/nos-core/**/*.md (source of truth — usable even before a
bundle compile) into a tiny static site: reverse-chronological index,
one page per entry, RSS feed. Consumed by .github/workflows/pages.yml on
release-tag pushes; runnable locally for preview:

  tools/devlog-render.py --out _site && open _site/index.html

No Jekyll/Ruby — the repo is Python-native. Reuses the compiler's validated
loader so a schema violation fails the publish instead of shipping garbage.
"""

from __future__ import annotations

import argparse
import datetime
import html
import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

SITE_TITLE = "nOS devlog"
SITE_TAGLINE = "Engineering narrative of the This is AIT agentic home lab"
REPO_URL = "https://github.com/thisisait/nOS"

CSS = """
:root { --fg:#1a1a1a; --muted:#666; --accent:#0b6e4f; --bg:#fdfdfc; --code:#f4f4f0; }
* { box-sizing: border-box; }
body { font: 17px/1.65 Georgia, 'Times New Roman', serif; color: var(--fg);
       background: var(--bg); max-width: 46rem; margin: 0 auto; padding: 2rem 1.2rem 4rem; }
header.site { border-bottom: 2px solid var(--fg); margin-bottom: 2rem; padding-bottom: .8rem; }
header.site h1 { margin: 0; font-size: 1.6rem; }
header.site h1 a { color: var(--fg); text-decoration: none; }
header.site p { margin: .2rem 0 0; color: var(--muted); font-style: italic; }
h1, h2, h3 { font-family: Helvetica, Arial, sans-serif; line-height: 1.25; }
a { color: var(--accent); }
.entry-meta { color: var(--muted); font-size: .85rem;
              font-family: Helvetica, Arial, sans-serif; }
.tag { display: inline-block; background: var(--code); border-radius: 3px;
       padding: 0 .45em; margin-right: .3em; font-size: .8rem; }
ul.index { list-style: none; padding: 0; }
ul.index li { margin-bottom: 1.6rem; }
ul.index h2 { margin: 0 0 .15rem; font-size: 1.15rem; }
pre { background: var(--code); padding: .8rem 1rem; overflow-x: auto;
      font-size: .82rem; line-height: 1.45; border-radius: 4px; }
code { background: var(--code); padding: .08em .3em; border-radius: 3px; font-size: .85em; }
pre code { padding: 0; background: none; }
table { border-collapse: collapse; font-size: .9rem; }
td, th { border: 1px solid #ccc; padding: .3rem .6rem; }
footer { margin-top: 3rem; border-top: 1px solid #ccc; padding-top: 1rem;
         color: var(--muted); font-size: .85rem; }
"""

PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="alternate" type="application/rss+xml" title="{site}" href="feed.xml">
<style>{css}</style>
</head><body>
<header class="site"><h1><a href="index.html">{site}</a></h1><p>{tagline}</p></header>
{body}
<footer>Part of <a href="{repo}">{repo_name}</a> — every service self-hosted, every byte local.
Subscribe via <a href="feed.xml">RSS</a>.</footer>
</body></html>
"""


def _load_compiler():
    spec = importlib.util.spec_from_file_location(
        "devlog_compile", REPO / "tools" / "devlog-compile.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _page(title: str, body: str) -> str:
    return PAGE.format(
        title=html.escape(title), site=SITE_TITLE, tagline=SITE_TAGLINE,
        css=CSS, body=body, repo=REPO_URL, repo_name="thisisait/nOS",
    )


def _meta_line(entry: dict) -> str:
    tags = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in entry["tags"])
    release = (
        f' · <a href="{REPO_URL}/releases/tag/{html.escape(entry["release"])}">'
        f'{html.escape(entry["release"])}</a>'
        if entry.get("release") else ""
    )
    return f'<div class="entry-meta">{entry["date"]}{release} {tags}</div>'


def render(out_dir: pathlib.Path) -> list[dict]:
    mod = _load_compiler()
    md = mod._markdown_renderer()
    entries = [e for e in mod.load_entries() if e["status"] == "published"]
    entries.sort(key=lambda e: (e["date"], e["id"]), reverse=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        md.reset()
        body_html = md.convert(entry["body_md"])
        body = (
            f"<article><h1>{html.escape(entry['title'])}</h1>"
            f"{_meta_line(entry)}\n{body_html}</article>"
        )
        (out_dir / f"{entry['id']}.html").write_text(
            _page(entry["title"], body), encoding="utf-8"
        )

    items = "".join(
        f'<li><h2><a href="{e["id"]}.html">{html.escape(e["title"])}</a></h2>'
        f"{_meta_line(e)}<p>{html.escape(e['summary'])}</p></li>\n"
        for e in entries
    )
    (out_dir / "index.html").write_text(
        _page(SITE_TITLE, f'<ul class="index">{items}</ul>'), encoding="utf-8"
    )

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    rss_items = "".join(
        "<item>"
        f"<title>{html.escape(e['title'])}</title>"
        f"<link>{REPO_URL}</link>"
        f"<guid isPermaLink=\"false\">{e['id']}</guid>"
        f"<pubDate>{datetime.datetime.strptime(e['date'], '%Y-%m-%d').strftime('%a, %d %b %Y')} 12:00:00 +0000</pubDate>"
        f"<description>{html.escape(e['summary'])}</description>"
        "</item>\n"
        for e in entries
    )
    (out_dir / "feed.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        f"<title>{SITE_TITLE}</title><link>{REPO_URL}</link>"
        f"<description>{SITE_TAGLINE}</description><lastBuildDate>{now}</lastBuildDate>\n"
        f"{rss_items}</channel></rss>\n",
        encoding="utf-8",
    )
    return entries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_site")
    args = ap.parse_args()
    entries = render(pathlib.Path(args.out))
    print(f"rendered {len(entries)} entries -> {args.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
