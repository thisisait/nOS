"""The face Iris renders a model's text as text, links nothing and names no desktop bridge.

WHY. Everything Iris draws came from a model, through the thalamus. A raw-HTML sink
({@html}, innerHTML, ...) would let a model's string become markup in the person's window,
and a link, script or embed is a way out of it. Iris's components live in face/src/lib/iris
and draw with the face ui/ primitives, so both are scanned. The pupil (a Tauri window that
borrowed them) retired 2026-11-08 with its CSP and dev-server checks; Iris now has no
desktop bridge, so none may come back unseen. test_face_security_gates.py scans all of
face/src for raw-HTML sinks too; the link scan is Iris's own.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
RAW_HTML = re.compile(r"\{@html|innerHTML|outerHTML|insertAdjacentHTML|document\.write|DOMParser")
# Markup that loads, links or embeds: a model string never needs one, and each is a way out.
LINKING = re.compile(r"<foreignObject|<image\b|<a\b|<script|\bhref=|xlink:href")
#: a .svelte file's own <script> / <script module> blocks open at column 0; markup is indented
OWN_SCRIPT = re.compile(r"^</?script\b[^>]*>", re.M)
FACE_UI = REPO / "files/anatomy/face/src/lib/components/ui"  # reached by `$lib/components/ui`
IRIS = REPO / "files/anatomy/face/src/lib/iris"
TAURI = re.compile(r"__TAURI__|@tauri-apps")


def _sources() -> list[pathlib.Path]:
    own = [p for ext in ("svelte", "ts", "js", "html") for p in IRIS.glob(f"**/*.{ext}")]
    face = [p for ext in ("svelte", "ts") for p in FACE_UI.glob(f"**/*.{ext}")]
    return sorted(own + face)


def _shipped() -> list[pathlib.Path]:
    # Shipped files only: the tests name these strings to assert they never render.
    return [p for ext in ("svelte", "ts", "js") for p in IRIS.rglob(f"*.{ext}") if not p.name.endswith(".test.ts")]


def _hits(text: str) -> list[str]:
    # An HTML comment saying "there is no {@html} path" is prose, not a sink.
    return RAW_HTML.findall(re.sub(r"<!--.*?-->", "", text, flags=re.S))


def _linking(text: str) -> list[str]:
    return LINKING.findall(OWN_SCRIPT.sub("", re.sub(r"<!--.*?-->", "", text, flags=re.S)))


def test_the_scan_sees_every_renderer():
    # The renderers of model strings: a new one outside face/src/lib/iris would draw unscanned.
    names = {p.name for p in _sources()}
    assert {"Component.svelte", "Markdown.svelte", "Chart.svelte"} <= names, sorted(names)


def test_the_scan_sees_the_face_primitives():
    assert any(p.is_relative_to(FACE_UI) and p.suffix == ".svelte" for p in _sources()), FACE_UI


def test_the_scan_catches_a_planted_sink():
    assert _hits("<p>{@html model}</p>") and _hits("el.innerHTML = s")
    assert not _hits("<!-- escaped; there is no {@html} path -->")


def test_no_raw_html_sink_in_iris():
    bad = [f"{p.relative_to(REPO)}: {h}" for p in _sources() if p.is_file() for h in _hits(p.read_text(encoding="utf-8"))]
    assert not bad, "raw-HTML sink in Iris (render text as text):\n  " + "\n  ".join(bad)


def test_the_link_scan_catches_a_planted_link():
    for planted in ('\t<a href="https://x">x</a>', "\t<foreignObject>", '\t<image href="x"/>', "\t\t<script>x</script>",
                    '<use xlink:href="#a"/>'):
        assert _linking(planted), planted
    assert not _linking('<script lang="ts">\n\tlet a = 1;\n</script>\n<circle fill="url(#eye-core)" />')


def test_no_link_or_foreign_markup_in_iris():
    files = _shipped()
    assert any(p.name == "Eye.svelte" for p in files), "the link scan does not see Eye.svelte"
    assert any(p.name == "Iris.svelte" for p in files), "the link scan does not see Iris.svelte"
    bad = [f"{p.relative_to(REPO)}: {h}" for p in files for h in _linking(p.read_text(encoding="utf-8"))]
    assert not bad, "a link, script or embed in Iris (draw text, link nothing):\n  " + "\n  ".join(bad)


def test_iris_names_no_desktop_bridge():
    """The pupil's Tauri bridge retired: a component that reaches for one again is refused here."""
    bad = [str(p.relative_to(REPO)) for p in _shipped() if TAURI.search(p.read_text(encoding="utf-8"))]
    assert not bad, f"a desktop bridge named in Iris: {bad}"
    assert TAURI.search("(globalThis as { __TAURI__?: T }).__TAURI__") and TAURI.search("import '@tauri-apps/api'")
