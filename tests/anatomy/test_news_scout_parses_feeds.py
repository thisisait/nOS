"""news-scout's feed parsing works on BOTH RSS and Atom, and dedups by link —
offline, against fixture XML, so the parser is pinned without hitting a network
(the live fetch is exercised by running the tool; this pins the extraction)."""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location(
        "news_scout", REPO / "tools" / "loops" / "news-scout.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>RSS one</title><link>https://a.example/1</link>
        <pubDate>Mon, 07 Sep 2026 10:00:00 +0000</pubDate>
        <description>first</description></item>
  <item><title>RSS two</title><link>https://a.example/2</link></item>
</channel></rss>"""

_ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>Atom one</title>
    <link rel="alternate" href="https://b.example/x"/>
    <updated>2026-09-07T10:00:00Z</updated>
    <summary>sum</summary></entry>
</feed>"""


def test_rss_items_and_links():
    m = _mod()
    src = {"id": "s", "label": "S"}
    # exercise the parse path fetch() uses, without the network
    items = [e for e in m._items(_RSS)]
    assert len(items) == 2
    assert m._link_of(items[0]) == "https://a.example/1"
    assert m._text(m._child(items[0], "title")) == "RSS one"


def test_atom_link_uses_href():
    m = _mod()
    items = m._items(_ATOM)
    assert len(items) == 1
    assert m._link_of(items[0]) == "https://b.example/x"  # href attr, not text


def test_dedup_collapses_same_link():
    m = _mod()
    rows = [
        {"source": "a", "title": "One", "link": "https://x.example/1/"},
        {"source": "b", "title": "One again", "link": "https://x.example/1#frag"},
        {"source": "c", "title": "Two", "link": "https://x.example/2"},
    ]
    out = m.dedup(rows)
    assert [r["source"] for r in out] == ["a", "c"], "same canonical link must collapse; first wins"
