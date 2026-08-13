"""The Host mcpo dials must be a Host mcp-grafana allows.

MEASURED 2026-08-13, while verifying the REM-196 repin (commit 8c72a318) was a
drop-in. It was — at the image level. One layer up, the link was already dead:

    docker logs iiab-mcpo-1 (2026-08-12):
        Failed to connect to MCP server 'grafana' … 403 Forbidden
        for url 'http://mcp-grafana:8000/sse'
    probe from iiab_iiab_net against the resident container:
        HTTP/1.1 403 Forbidden — forbidden: host not allowed

`mcp-grafana`'s Host allowlist defaults to loopback variants of `--address`
(DNS-rebinding protection, present in BOTH the resident 76ed7db build and
1.1.0), and mcpo dials the Docker service name — a Host the default refuses.
mcpo logs the failure, starts healthy anyway, and silently drops the whole
grafana toolset: a healthy gateway with no grafana tools, invisible for as
long as it ran. Same shape as CLAUDE.md's "success markers must be written by
a reader" — mcpo's health says mcpo started, not that its children answered.

A/B on throwaway containers the same day: with
`--allowed-hosts mcp-grafana:8000`, Host `mcp-grafana:8000` → 200
text/event-stream; any other Host → 403. Without the flag, both → 403.

WHAT IS PINNED: the compose override restates the entrypoint (compose
`entrypoint:` replaces the image's, flags and all) and its allowed-hosts value
contains the exact host:port that `mcpo-config.json.j2` dials. Cross-file on
purpose — editing either side out of step re-opens the silent 403.

WHAT THIS CANNOT DO: prove the live container serves 200 to mcpo. That is a
converge followed by `docker logs iiab-mcpo-1` showing the grafana toolset
mount — named here so the converge operator knows what to look at.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = REPO / "roles/pazny.mcp_gateway/templates/compose.yml.j2"
MCPO_CONFIG = REPO / "roles/pazny.mcp_gateway/templates/mcpo-config.json.j2"


def _grafana_block() -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    start = text.index("mcp-grafana:")
    end = text.find("{% endif %}", start)
    return text[start : end if end != -1 else len(text)]


def _dialed_hostport() -> str:
    m = re.search(r'"url":\s*"http://([^/"]+)/sse"', MCPO_CONFIG.read_text(encoding="utf-8"))
    assert m, (
        "mcpo-config.json.j2 no longer declares the grafana SSE url — if the "
        "dial moved (streamable-http lives at /mcp), move this gate with it."
    )
    return m.group(1)


def test_the_compose_override_allows_the_host_mcpo_dials() -> None:
    block = _grafana_block()
    dialed = _dialed_hostport()

    assert "--allowed-hosts" in block, (
        "the mcp-grafana compose block no longer passes --allowed-hosts. The "
        "binary's default allowlist is loopback-only, so mcpo's dial to "
        f"http://{dialed}/sse gets '403 forbidden: host not allowed' — and "
        "mcpo starts healthy anyway with the grafana toolset silently gone "
        "(measured live 2026-08-12/13)."
    )
    flags = re.search(r"--allowed-hosts\s*\n\s*-\s*(\S+)", block)
    assert flags and dialed in flags.group(1), (
        f"--allowed-hosts is passed but its value {flags.group(1) if flags else '?'!s} "
        f"does not contain {dialed!r}, the host:port mcpo-config.json.j2 dials. "
        "The two files drifted; the 403 is back."
    )


def test_the_entrypoint_restates_transport_and_address() -> None:
    """Compose `entrypoint:` replaces the image's entrypoint wholesale.

    Passing only --allowed-hosts would drop --transport sse and the 0.0.0.0
    bind, and the container would come up in stdio mode answering nobody —
    a fix for the 403 that kills the port instead.
    """
    block = _grafana_block()
    for needed in ("/app/mcp-grafana", "--transport", "sse", "--address", "0.0.0.0:8000"):
        assert re.search(rf"^\s*-\s*{re.escape(needed)}\s*$", block, re.MULTILINE), (
            f"the restated entrypoint lost {needed!r}. The override replaces "
            "the image entrypoint completely; every original flag must be "
            "restated alongside --allowed-hosts."
        )
