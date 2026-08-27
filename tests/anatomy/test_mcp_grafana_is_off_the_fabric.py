"""REM-230 — mcp-grafana must not sit on the shared network.

MEASURED 2026-08-27 (cycle-42 attack probe): a throwaway container on
shared_net completed the MCP handshake with NO credential and listed 65
tools, then read every Grafana datasource — served with the estate's own
service-account token. `--allowed-hosts` is a Host-header allowlist, not
authentication. mcpo is the only caller and reaches it over iiab_net.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
TPL = REPO / "roles/pazny.mcp_gateway/templates/compose.yml.j2"


def _block(name: str) -> str:
    src = TPL.read_text(encoding="utf-8")
    start = src.index(f"\n  {name}:")
    nxt = re.search(r"\n  [a-z][a-z0-9-]*:\n", src[start + 1:])
    return src[start:start + 1 + (nxt.start() if nxt else len(src))]


def test_the_sidecar_is_not_on_the_shared_fabric():
    assert "stacks_shared_network" not in _block("mcp-grafana"), (
        "mcp-grafana is back on the shared network — unauthenticated, it "
        "serves 65 Grafana tools to any container on it (REM-230)"
    )


def test_the_caller_can_still_reach_it():
    """Positive control: dropping the wrong network would break the toolset
    silently — mcpo starts healthy either way."""
    for svc in ("mcpo", "mcp-grafana"):
        assert "iiab_net" in _block(svc), f"{svc} left iiab_net; mcpo's dial breaks"
