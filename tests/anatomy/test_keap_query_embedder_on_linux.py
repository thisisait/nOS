"""Anatomy gate — KEAP embeds query text with the host Ollama by default, on both platforms.

THE SYMPTOM (2026-10-21, spark1). Iris answered "not in our knowledge base" to
paraphrased knowledge questions whose node was in KEAP: search_knowledge ran
on the lexical and graph legs only, because ``keap_ollama_url`` defaulted to
"" ("Linux host-gateway cannot reach a loopback-bound Ollama"). On Linux nOS
binds Ollama to the docker bridge (``ollama_bind_host`` = docker0), and the
gated KEAP container reaches it there; the stored vectors were already in KEAP.
The iris-bench knowledge domain went from 9/24 to 13/24 with the vector leg.

THE CHECK. Rendered for Linux with Ollama installed, the default is
``ollama_url``; for macOS it is http://host.docker.internal:11434 (Docker
Desktop's way to the host loopback; the operator host runs it from config.yml); without Ollama it is "". Operator 2026-10-21: on by default.

CEILING. Renders the default with stock Jinja; the effect is the
``[legs: vector, …]`` line of tools/keap-semantic-search.py on a live estate.
"""

import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]


def _raw() -> str:
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity
    layers = [yaml.safe_load(f.read_text(encoding="utf-8")) or {} for f in nos_identity.default_layers()]
    return next(d["keap_ollama_url"] for d in layers if "keap_ollama_url" in d)


def _render(system: str, install_ollama: bool) -> str:
    raw = _raw()
    ctx = {"ansible_system": system, "install_ollama": install_ollama, "ollama_url": "http://172.17.0.1:11434"}
    return jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(raw).render(ctx)


def test_linux_with_ollama_embeds_queries_on_the_bridge():
    assert _render("Linux", True) == "http://172.17.0.1:11434"


def test_macos_embeds_through_docker_desktop():
    assert _render("Darwin", True) == "http://host.docker.internal:11434"


def test_macos_without_ollama_no_embedder():
    assert _render("Darwin", False) == ""


def test_no_ollama_no_embedder():
    assert _render("Linux", False) == ""
