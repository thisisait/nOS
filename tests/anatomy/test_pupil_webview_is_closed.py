"""The pupil's webview renders text as text and talks to nothing but its own bridge.

WHY. Everything the pupil draws came from a model, through the thalamus. A raw-HTML
sink ({@html}, innerHTML, ...) would let a model's string become markup in a window
on the operator's Mac; a CSP that allows http/ws would let that markup phone out.
The only way in is the Rust bridge (src-tauri/src/bridge.rs), never a port: with no
devUrl, `tauri dev` serves dist over LAN-visible http on :1430 unless --no-dev-server.
Iris's components live in face/src/lib/iris (the pupil borrows them, `$iris`), so they are
scanned as the pupil's own; only pupil/src/transport.tauri.ts may name the bridge.
"""
from __future__ import annotations

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
PUPIL = REPO / "files/anatomy/pupil"
CONF = PUPIL / "src-tauri/tauri.conf.json"
RAW_HTML = re.compile(r"\{@html|innerHTML|outerHTML|insertAdjacentHTML|document\.write|DOMParser")
# Markup that loads, links or embeds: a model string never needs one, and each is a way out.
LINKING = re.compile(r"<foreignObject|<image\b|<a\b|<script|\bhref=|xlink:href")
#: a .svelte file's own <script> / <script module> blocks open at column 0; markup is indented
OWN_SCRIPT = re.compile(r"^</?script\b[^>]*>", re.M)
PKG = PUPIL / "package.json"
FACE_UI = REPO / "files/anatomy/face/src/lib/components/ui"  # reached by `$lib/components/ui`
IRIS = REPO / "files/anatomy/face/src/lib/iris"  # vite.config.ts `$iris`
#: the one file that may touch the desktop bridge; everything else runs on a Transport
TAURI = re.compile(r"__TAURI__|@tauri-apps")
TAURI_OK = PUPIL / "src/transport.tauri.ts"
# Every CSP source the pupil may name; style-src alone may also inline.
CSP_OK = {"'self'", "ipc:", "http://ipc.localhost", "data:"}
CSP_EXTRA = {"style-src": {"'unsafe-inline'"}}


def _sources() -> list[pathlib.Path]:
    # The face ui/ primitives draw in the pupil's window too, so they are scanned with it.
    own = [p for ext in ("svelte", "ts", "js", "html") for d in (PUPIL / "src", IRIS) for p in d.glob(f"**/*.{ext}")]
    face = [p for ext in ("svelte", "ts") for p in FACE_UI.glob(f"**/*.{ext}")]
    return sorted(own + face) + [PUPIL / "index.html"]


def _csp_bad(csp: str) -> list[str]:
    bad = []
    for d in filter(None, (x.strip() for x in csp.split(";"))):
        name, *srcs = d.split()
        bad += [f"{name} {s}" for s in srcs if s not in CSP_OK | CSP_EXTRA.get(name, set())]
    return bad


def _hits(text: str) -> list[str]:
    # An HTML comment saying "there is no {@html} path" is prose, not a sink.
    return RAW_HTML.findall(re.sub(r"<!--.*?-->", "", text, flags=re.S))


def test_the_scan_sees_the_pupil():
    assert any(p.suffix == ".svelte" for p in _sources()), f"no Svelte under {PUPIL}/src"


def test_the_scan_sees_every_renderer():
    # The renderers of model strings: a new one outside src/ would draw unscanned.
    names = {p.name for p in _sources()}
    assert {"Component.svelte", "Markdown.svelte", "Chart.svelte"} <= names, sorted(names)


def test_the_scan_catches_a_planted_sink():
    assert _hits("<p>{@html model}</p>") and _hits("el.innerHTML = s")
    assert not _hits("<!-- escaped; there is no {@html} path -->")


def test_no_raw_html_sink_in_the_pupil():
    bad = [f"{p.relative_to(REPO)}: {h}" for p in _sources() if p.is_file() for h in _hits(p.read_text(encoding="utf-8"))]
    assert not bad, "raw-HTML sink in the pupil (render text as text):\n  " + "\n  ".join(bad)


def test_the_scan_sees_the_face_primitives():
    assert any(p.is_relative_to(FACE_UI) and p.suffix == ".svelte" for p in _sources()), FACE_UI


def test_the_csp_check_catches_a_planted_origin():
    for planted in ("connect-src *", "connect-src evil.example", "script-src 'unsafe-eval'", "img-src https:"):
        assert _csp_bad(f"default-src 'self'; {planted}"), planted


def test_the_csp_allows_no_remote_origin():
    conf = json.loads(CONF.read_text(encoding="utf-8"))
    csp = conf["app"]["security"]["csp"]
    assert "default-src 'self'" in csp, csp
    assert not _csp_bad(csp), f"CSP names a source outside {sorted(CSP_OK)}: {_csp_bad(csp)}"
    assert "devUrl" not in conf["build"], "a devUrl means a dev server port"


def test_tauri_dev_opens_no_port():
    scripts = json.loads(PKG.read_text(encoding="utf-8"))["scripts"]
    assert "tauri dev --no-dev-server" in scripts.get("dev", ""), f"package.json scripts.dev: {scripts.get('dev')!r}"
    loose = [k for k, v in scripts.items() if re.search(r"\btauri\b", v) and "--no-dev-server" not in v and "tauri build" not in v]
    assert not loose, f"a script that can start tauri's :1430 dev server: {loose}"


def test_tauri_dev_waits_for_the_page_it_embeds():
    """With no devUrl, tauri-codegen embeds dist at compile time, and `tauri dev` does not wait for
    beforeDevCommand unless told: cargo embedded a dist vite was still emptying ("asset not found:
    index.html", live 2026-10-12)."""
    before = json.loads(CONF.read_text(encoding="utf-8"))["build"]["beforeDevCommand"]
    assert isinstance(before, dict) and before.get("wait") is True, before
    assert "build" in before.get("script", ""), before


def _linking(text: str) -> list[str]:
    return LINKING.findall(OWN_SCRIPT.sub("", re.sub(r"<!--.*?-->", "", text, flags=re.S)))


def test_the_link_scan_catches_a_planted_link():
    for planted in ('\t<a href="https://x">x</a>', "\t<foreignObject>", '\t<image href="x"/>', "\t\t<script>x</script>",
                    '<use xlink:href="#a"/>'):
        assert _linking(planted), planted
    assert not _linking('<script lang="ts">\n\tlet a = 1;\n</script>\n<circle fill="url(#eye-core)" />')


def test_no_link_or_foreign_markup_in_the_pupil():
    # Shipped files only: the tests name these strings to assert they never render.
    files = [p for ext in ("svelte", "ts", "js") for d in (PUPIL / "src", IRIS) for p in d.rglob(f"*.{ext}")
             if not p.name.endswith(".test.ts")]
    assert any(p.name == "Eye.svelte" for p in files), "the link scan does not see Eye.svelte"
    assert any(p.name == "Iris.svelte" for p in files), "the link scan does not see Iris.svelte"
    bad = [f"{p.relative_to(REPO)}: {h}" for p in files for h in _linking(p.read_text(encoding="utf-8"))]
    assert not bad, "a link, script or embed in the pupil (draw text, link nothing):\n  " + "\n  ".join(bad)


def test_only_the_tauri_transport_names_the_bridge():
    """Iris.svelte runs on a Transport: the face mounts it with no bridge, the pupil hands it Tauri's."""
    files = [p for ext in ("svelte", "ts", "js") for d in (PUPIL / "src", IRIS) for p in d.rglob(f"*.{ext}")
             if not p.name.endswith(".test.ts")]
    assert TAURI_OK in files, f"no {TAURI_OK.relative_to(REPO)}"
    bad = [str(p.relative_to(REPO)) for p in files if p != TAURI_OK and TAURI.search(p.read_text(encoding="utf-8"))]
    assert not bad, f"the Tauri bridge named outside {TAURI_OK.name}: {bad}"
    assert TAURI.search("(globalThis as { __TAURI__?: T }).__TAURI__") and TAURI.search("import '@tauri-apps/api'")
