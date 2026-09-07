#!/usr/bin/env python3
"""Build the nos-dgx knowledge base: kb/*.md → www/kb/*.html with navigation.

One markdown file = one page. Frontmatter (between `---` lines) carries:

    title:    the page name (required)
    section:  start | dev | admin | tips        (order + titles: kb/sections.yml)
    order:    integer, position inside the section
    summary:  one line for the index card

Static output on purpose: no build step for the reader, no CDN, works on a
LAN with no internet, and the pages are plain files nginx already serves.
`__HOST__` / `__SHORT__` in the markdown are rendered like the templates.

    kb-build.py --src kb --out www/kb --host spark1.local --short spark1
"""
import argparse
import html
import pathlib
import re
import sys

import markdown
import yaml

CSS = """
:root { color-scheme: light dark; --fg:#1b1b1b; --bg:#f7f7f5; --muted:#666; --card:#fff; --line:#ddd; --accent:#2f6f4f; --code:#f0f0ec; }
@media (prefers-color-scheme: dark) { :root { --fg:#e8e8e4; --bg:#141414; --muted:#9a9a9a; --card:#1e1e1e; --line:#333; --accent:#7fc8a0; --code:#232323; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.55 system-ui, sans-serif; }
a { color:var(--accent); }
.wrap { display:grid; grid-template-columns: 250px minmax(0,1fr); min-height:100vh; }
nav.side { border-right:1px solid var(--line); padding:1.5rem 1rem; background:var(--card); }
nav.side .brand { display:block; font-weight:600; text-decoration:none; color:inherit; margin-bottom:1.25rem; }
nav.side .brand small { display:block; color:var(--muted); font-weight:400; }
nav.side h4 { margin:1.1rem 0 .35rem; font-size:.78rem; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); }
nav.side a.p { display:block; padding:.25rem .5rem; border-radius:6px; text-decoration:none; color:inherit; font-size:.95rem; }
nav.side a.p:hover { background:var(--bg); }
nav.side a.p.cur { background:var(--accent); color:#fff; }
main { padding:2.25rem 2.5rem; max-width:860px; }
main h1 { font-size:1.7rem; margin:.2rem 0 .25rem; }
main .meta { color:var(--muted); margin-bottom:1.5rem; }
main h2 { font-size:1.2rem; margin:1.8rem 0 .5rem; border-bottom:1px solid var(--line); padding-bottom:.25rem; }
main h3 { font-size:1.02rem; margin:1.3rem 0 .4rem; }
pre { background:var(--code); border:1px solid var(--line); border-radius:8px; padding:.8rem 1rem; overflow-x:auto; font-size:.9rem; }
code { background:var(--code); border-radius:4px; padding:0 .3em; font-size:.92em; }
pre code { background:none; padding:0; }
table { border-collapse:collapse; width:100%; margin:.75rem 0; font-size:.95rem; }
th, td { border:1px solid var(--line); padding:.4rem .6rem; text-align:left; vertical-align:top; }
th { background:var(--card); }
blockquote { margin:1rem 0; padding:.5rem 1rem; border-left:3px solid var(--accent); background:var(--card); color:var(--muted); }
.cards { display:grid; grid-template-columns: repeat(auto-fill, minmax(240px,1fr)); gap:.75rem; margin:.75rem 0 1.5rem; }
.card { display:block; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:.9rem 1rem; text-decoration:none; color:inherit; }
.card:hover { border-color:var(--accent); } .card b { color:var(--accent); display:block; } .card small { color:var(--muted); }
.pn { display:flex; justify-content:space-between; gap:1rem; margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--line); font-size:.95rem; }
.pn a { text-decoration:none; } .pn span { color:var(--muted); display:block; font-size:.8rem; }
@media (max-width: 760px) { .wrap { grid-template-columns:1fr; } nav.side { border-right:0; border-bottom:1px solid var(--line); } main { padding:1.5rem 1.25rem; } }
"""


def frontmatter(text: str):
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    return (yaml.safe_load(parts[1]) or {}), parts[2]


def load(src: pathlib.Path, sections: list[dict]):
    order = {s["id"]: i for i, s in enumerate(sections)}
    pages = []
    for f in sorted(src.glob("*.md")):
        if f.name.startswith("_"):
            continue
        meta, body = frontmatter(f.read_text(encoding="utf-8"))
        if "title" not in meta:
            sys.exit(f"{f}: frontmatter needs a title")
        sec = meta.get("section", "tips")
        if sec not in order:
            sys.exit(f"{f}: unknown section {sec!r} (see sections.yml)")
        pages.append({
            "slug": f.stem, "title": str(meta["title"]), "section": sec,
            "order": int(meta.get("order", 99)), "summary": str(meta.get("summary", "")),
            "body": body,
        })
    pages.sort(key=lambda p: (order[p["section"]], p["order"], p["slug"]))
    return pages


def render_md(body: str) -> str:
    return markdown.markdown(body, extensions=["fenced_code", "tables", "sane_lists", "toc"])


def sidebar(pages, sections, cur: str, short: str) -> str:
    out = [f'<a class="brand" href="/kb/">nOS on {html.escape(short)}<small>knowledge base</small></a>',
           '<a class="p" href="/">← services</a>']
    for s in sections:
        mine = [p for p in pages if p["section"] == s["id"]]
        if not mine:
            continue
        out.append(f'<h4>{html.escape(s["title"])}</h4>')
        for p in mine:
            cls = "p cur" if p["slug"] == cur else "p"
            out.append(f'<a class="{cls}" href="/kb/{p["slug"]}.html">{html.escape(p["title"])}</a>')
    return "\n".join(out)


def page_html(title: str, side: str, main: str, short: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · nOS on {html.escape(short)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<nav class="side">
{side}
</nav>
<main>
{main}
</main>
</div>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--host", required=True)
    ap.add_argument("--short", required=True)
    a = ap.parse_args()
    src, out = pathlib.Path(a.src), pathlib.Path(a.out)
    sections = yaml.safe_load((src / "sections.yml").read_text(encoding="utf-8"))
    pages = load(src, sections)
    out.mkdir(parents=True, exist_ok=True)
    sub = lambda t: t.replace("__HOST__", a.host).replace("__SHORT__", a.short)  # noqa: E731

    # index: cards grouped by section
    parts = ['<h1>Knowledge base</h1>',
             f'<p class="meta">How to use and run nOS on {html.escape(a.short)} — for new users, developers and the admin. '
             'The source is one markdown file per page in <code>bootstrap/minimal-linux-dgx/kb/</code>.</p>']
    for s in sections:
        mine = [p for p in pages if p["section"] == s["id"]]
        if not mine:
            continue
        parts.append(f'<h2>{html.escape(s["title"])}</h2><div class="cards">')
        for p in mine:
            parts.append(f'<a class="card" href="/kb/{p["slug"]}.html"><b>{html.escape(p["title"])}</b>'
                         f'<small>{html.escape(sub(p["summary"]))}</small></a>')
        parts.append('</div>')
    (out / "index.html").write_text(page_html("Knowledge base", sidebar(pages, sections, "", a.short),
                                              "\n".join(parts), a.short), encoding="utf-8")

    # pages with prev/next
    sec_title = {s["id"]: s["title"] for s in sections}
    for i, p in enumerate(pages):
        body = render_md(sub(p["body"]))
        body = re.sub(r"^\s*<h1>.*?</h1>", "", body, count=1, flags=re.S)  # the title is rendered by us
        prev = pages[i - 1] if i > 0 else None
        nxt = pages[i + 1] if i + 1 < len(pages) else None
        pn = '<div class="pn">'
        pn += (f'<a href="/kb/{prev["slug"]}.html"><span>previous</span>← {html.escape(prev["title"])}</a>' if prev else '<i></i>')
        pn += (f'<a href="/kb/{nxt["slug"]}.html" style="text-align:right"><span>next</span>{html.escape(nxt["title"])} →</a>' if nxt else '<i></i>')
        pn += '</div>'
        main_html = (f'<h1>{html.escape(p["title"])}</h1><p class="meta">{html.escape(sec_title[p["section"]])}</p>'
                     f'{body}{pn}')
        (out / f'{p["slug"]}.html').write_text(page_html(p["title"], sidebar(pages, sections, p["slug"], a.short),
                                                        main_html, a.short), encoding="utf-8")
    print(f"kb: {len(pages)} page(s) → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
