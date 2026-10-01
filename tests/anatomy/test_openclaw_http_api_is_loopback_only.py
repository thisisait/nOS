"""OpenClaw's OpenAI HTTP API is enabled on loopback only, and the token is never logged.

MEASURED 2026-10-01: OpenClaw 2026.7.1 answered 404 on /v1/chat/completions
(disabled by default upstream), so AgentKit's openclaw-* provider had no wire.
Upstream (docs/gateway/openai-http-api.md) is explicit that a gateway token on
this endpoint is FULL OPERATOR ACCESS — "keep it on loopback". So the role
re-asserts `gateway.bind loopback` before it enables the endpoint, under
`set -e`, in one task; this gate renders that task and reads what it would run.
"""

from __future__ import annotations

import re
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "roles/pazny.openclaw/tasks/main.yml"
DEFAULTS = REPO / "roles/pazny.openclaw/defaults/main.yml"
REGISTRY = REPO / "state/llm-backends.yml"
KEY = "gateway.http.endpoints.chatCompletions.enabled"


def _tasks() -> list[dict]:
    return [t for t in yaml.safe_load(TASKS.read_text()) if isinstance(t, dict)]


def _shell(t: dict) -> str:
    return str(t.get("ansible.builtin.shell") or t.get("shell") or "")


def _render(src: str, enabled: bool) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = bool
    return env.from_string(src).render(homebrew_prefix="/opt/homebrew", openclaw_http_api_enabled=enabled)


def test_the_endpoint_is_enabled_only_after_loopback_held():
    owners = [t for t in _tasks() if KEY in _shell(t)]
    assert len(owners) == 1, f"{len(owners)} tasks touch {KEY}; one place decides it"
    task = owners[0]
    out = _render(_shell(task), enabled=True)
    assert out.lstrip().startswith("set -e"), "without set -e a failed bind still enables the endpoint"
    bind = out.find("""config set gateway.bind '"loopback"'""")
    enable = out.find(f"config set {KEY}")
    assert 0 <= bind < enable, "the endpoint is enabled before (or without) re-asserting loopback"
    assert 'want=true' in out and 'want=false' in _render(_shell(task), enabled=False)
    assert task.get("failed_when") is not False, "a security toggle that cannot fail is not a toggle"


def test_no_task_binds_the_gateway_anywhere_but_loopback():
    src = TASKS.read_text()
    binds = re.findall(r"""(?:--gateway-bind\s+|gateway\.bind\s+'?"?)([a-z-]+)""", src)
    assert binds and set(binds) == {"loopback"}, f"gateway bind values in the role: {binds}"
    defaults = yaml.safe_load(DEFAULTS.read_text())
    assert defaults.get("openclaw_http_api_enabled") is True, "the operator's 2026-10-01 decision is the default"
    row = yaml.safe_load(REGISTRY.read_text())["backends"]["openclaw"]
    assert row["base_url"].startswith("http://127.0.0.1:"), row["base_url"]


def test_the_gateway_token_never_reaches_a_log():
    for t in _tasks():
        body = yaml.safe_dump(t)
        if "_oc_config_raw" in body or "openclaw_gateway_token" in body:
            assert t.get("no_log") is True, f"task {t.get('name')!r} handles the gateway token without no_log"
