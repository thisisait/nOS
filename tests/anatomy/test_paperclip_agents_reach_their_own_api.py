"""Paperclip's agents reach Paperclip, and Paperclip knows its own public URL.

2026-10-23, the operator's company in Paperclip: every agent and both Paperclip
MCP servers failed "Could not connect to server" on PAPERCLIP_API_URL =
http://paperclip.<tenant>:3100. With no explicit URL the server derived one from
its allowed hostname and its LISTEN port: the hostname resolves to the host's LAN
address, where 3100 is not published (the host port is paperclip_port, behind
Traefik on 443). Agents run inside the same container
(packages/adapter-utils buildPaperclipEnv: an explicit PAPERCLIP_API_URL wins),
so their API is the loopback listener. And BETTER_AUTH_URL was unset: Better Auth
warned on every start and guessed its origin per request.
"""
from __future__ import annotations

from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
TPL = REPO / "roles/pazny.paperclip/templates/compose.yml.j2"


def _env() -> dict:
    env = jinja2.Environment(undefined=jinja2.Undefined)
    env.filters["urlencode"] = str
    text = env.from_string(TPL.read_text()).render(paperclip_domain="paperclip.example.eu", paperclip_version="v",
                                                  paperclip_port=3006)
    return next(iter(yaml.safe_load(text)["services"].values()))["environment"]


def test_agents_get_the_loopback_api_of_their_own_container():
    env = _env()
    assert env.get("PAPERCLIP_API_URL") == f"http://localhost:{env['PAPERCLIP_LISTEN_PORT']}", env.get("PAPERCLIP_API_URL")


def test_the_server_knows_its_public_url():
    assert _env().get("BETTER_AUTH_URL") == "https://paperclip.example.eu"
