"""Anatomy gate — Open WebUI multi-hop prompt-injection retry cap (REM-055).

PENTEST-004 / REM-055: Open WebUI re-injects tool results as user
messages, so external data fetched by a tool can drive a chain of
further tool calls. Upstream's default `CHAT_RESPONSE_MAX_TOOL_CALL_RETRIES`
is 30 — 30 rounds of attacker-influenced tool execution per turn.

The fix (compose env in roles/pazny.open_webui/templates/compose.yml.j2)
hardens the default to 5: still enough for legitimate multi-step
workflows, but bounds the multi-hop injection loop. Operators with
high-trust tools can raise it via `openwebui_max_tool_call_retries`
in config.yml.

This gate pins three things so the hardening can't silently regress:
  1. The env var is present in the compose template.
  2. Its value defaults to 5 (NOT the upstream 30), via the
     operator-overridable `openwebui_max_tool_call_retries` var.
  3. REM-055 is no longer marked `pending` in the remediation queue
     (the fix is in the tree, so the queue must reflect it).
"""

from __future__ import annotations

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = REPO / "roles/pazny.open_webui/templates/compose.yml.j2"
QUEUE = REPO / "docs/llm/security/remediation-queue.json"

ENV_VAR = "CHAT_RESPONSE_MAX_TOOL_CALL_RETRIES"
OVERRIDE_VAR = "openwebui_max_tool_call_retries"


def _compose_text() -> str:
	return COMPOSE.read_text()


def test_retry_env_var_present():
	"""The retry-cap env var must be set in the Open WebUI compose."""
	assert ENV_VAR in _compose_text(), (
		f"{ENV_VAR} missing from {COMPOSE.relative_to(REPO)} — "
		"multi-hop prompt-injection retry cap (REM-055) regressed."
	)


def test_retry_cap_defaults_to_five_not_upstream_thirty():
	"""The default must be 5 (hardened), exposed via the operator-
	overridable var — never upstream's permissive 30."""
	text = _compose_text()
	# Find the env line and capture its rendered value expression.
	m = re.search(rf'{ENV_VAR}:\s*"([^"\n]*)"', text)
	assert m, f"{ENV_VAR} line not found / not double-quoted in compose"
	value = m.group(1)

	# Must route through the operator-override var with default 5.
	assert OVERRIDE_VAR in value, (
		f"{ENV_VAR} should resolve via {OVERRIDE_VAR} for operator "
		f"override, got: {value!r}"
	)
	assert re.search(r"default\(\s*5\s*\)", value), (
		f"{ENV_VAR} must default to 5 (hardened), got: {value!r}"
	)
	# Belt-and-braces: the upstream-permissive 30 must not be the default.
	assert "default(30)" not in value.replace(" ", ""), (
		f"{ENV_VAR} must not default to upstream 30, got: {value!r}"
	)


def test_rem_055_not_pending():
	"""With the fix in-tree, REM-055 must not still read `pending`."""
	data = json.loads(QUEUE.read_text())
	# The queue is a dict with a list under one of these keys, or a bare list.
	items = data
	if isinstance(data, dict):
		for key in ("remediations", "items", "queue", "findings"):
			if isinstance(data.get(key), list):
				items = data[key]
				break
	rem = next(
		(i for i in items if isinstance(i, dict) and i.get("id") == "REM-055"),
		None,
	)
	assert rem is not None, "REM-055 not found in remediation queue"
	assert rem.get("status") != "pending", (
		"REM-055 is fixed in roles/pazny.open_webui/templates/compose.yml.j2 "
		f"({ENV_VAR} default 5) but the queue still marks it pending."
	)
