"""Anatomy gate — on Linux KEAP embeds query text with the host Ollama by default.

THE SYMPTOM (2026-10-21, spark1). Iris answered "not in our knowledge base" to
paraphrased knowledge questions whose node was in KEAP: search_knowledge ran
on the lexical and graph legs only, because ``keap_ollama_url`` defaulted to
"" ("Linux host-gateway cannot reach a loopback-bound Ollama"). On Linux nOS
binds Ollama to the docker bridge (``ollama_bind_host`` = docker0), and the
gated KEAP container reaches it there; the stored vectors were already in KEAP.
The iris-bench knowledge domain went from 9/24 to 13/24 with the vector leg.

THE CHECK. Rendered for Linux with Ollama installed, the default is
``ollama_url``; for macOS it stays "" (Docker Desktop needs
host.docker.internal, an operator opt-in), and without Ollama it is "".

CEILING. Renders the default with stock Jinja; the effect is the
``[legs: vector, …]`` line of tools/keap-semantic-search.py on a live estate.
"""

from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]


def _render(system: str, install_ollama: bool) -> str:
    raw = yaml.safe_load((REPO / "default.config.yml").read_text(encoding="utf-8"))["keap_ollama_url"]
    ctx = {"ansible_system": system, "install_ollama": install_ollama, "ollama_url": "http://172.17.0.1:11434"}
    return jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(raw).render(ctx)


def test_linux_with_ollama_embeds_queries_on_the_bridge():
    assert _render("Linux", True) == "http://172.17.0.1:11434"


def test_macos_stays_an_opt_in():
    assert _render("Darwin", True) == ""


def test_no_ollama_no_embedder():
    assert _render("Linux", False) == ""
