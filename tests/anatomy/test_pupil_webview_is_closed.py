"""The pupil's webview renders text as text and talks to nothing but its own bridge.

WHY. Everything the pupil draws came from a model, through the thalamus. A raw-HTML
sink ({@html}, innerHTML, ...) would let a model's string become markup in a window
on the operator's Mac; a CSP that allows http/ws would let that markup phone out.
The only way in is the Rust bridge (src-tauri/src/bridge.rs), never a port.
"""
from __future__ import annotations

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
PUPIL = REPO / "files/anatomy/pupil"
CONF = PUPIL / "src-tauri/tauri.conf.json"
RAW_HTML = re.compile(r"\{@html|innerHTML|outerHTML|insertAdjacentHTML|document\.write|DOMParser")
REMOTE = re.compile(r"\b(?:https?|wss?):(?!//ipc\.localhost\b)")


def _sources() -> list[pathlib.Path]:
    return sorted(p for ext in ("svelte", "ts", "js", "html") for p in PUPIL.glob(f"src/**/*.{ext}")) + [PUPIL / "index.html"]


def _hits(text: str) -> list[str]:
    return RAW_HTML.findall(text)


def test_the_scan_sees_the_pupil():
    assert any(p.suffix == ".svelte" for p in _sources()), f"no Svelte under {PUPIL}/src"


def test_the_scan_catches_a_planted_sink():
    assert _hits("<p>{@html model}</p>") and _hits("el.innerHTML = s")


def test_no_raw_html_sink_in_the_pupil():
    bad = [f"{p.relative_to(REPO)}: {h}" for p in _sources() if p.is_file() for h in _hits(p.read_text(encoding="utf-8"))]
    assert not bad, "raw-HTML sink in the pupil (render text as text):\n  " + "\n  ".join(bad)


def test_the_csp_allows_no_remote_origin():
    conf = json.loads(CONF.read_text(encoding="utf-8"))
    csp = conf["app"]["security"]["csp"]
    assert "default-src 'self'" in csp, csp
    assert not REMOTE.findall(csp), f"CSP names a remote scheme: {csp}"
    assert "devUrl" not in conf["build"], "a devUrl means a dev server port; tauri dev runs the built page"
