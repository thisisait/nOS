"""A session's model changing is its own recorded event: agent_session_rebind.

Ruling 2026-10-16 (roadmap row agent-session-rebind-event). Before it, the Iris
picker logged the change as an agent_tool_result with tool "model", and Wing's
fallback logged only agent_model_fallback, so no reader could ask one question
of both. Payload: {from_model_uri, to_model_uri, by, reason}, by in
person | fallback | posture. Bone/Wing parity with the contract is held by
test_event_types_match_the_contract.py; this file holds the contract to the
type, the other mirrors, and the one run-time switch (Runner::serveFallback).
Shape only: AgentKit has no PHP unit harness here (see the fallback gate).
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TYPE = "agent_session_rebind"
PAYLOAD = ("from_model_uri", "to_model_uri", "by", "reason")


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_the_contract_lists_the_type():
    doc = yaml.safe_load(_read("files/anatomy/contracts/event-types.yml"))
    assert TYPE in doc["types"]


def test_the_thalamus_ledger_can_write_it():
    src = _read("files/anatomy/thalamus/thalamus/src/ledger.rs")
    assert re.search(r'Kind::SessionRebind\s*=>\s*"agent_session_rebind"', src)


def test_an_agent_can_subscribe_to_it():
    schema = yaml.safe_load(_read("state/schema/agent.schema.yaml"))
    enum = schema["properties"]["subscribe"]["items"]["properties"]["event_type"]["enum"]
    assert TYPE in enum


def test_the_fallback_switch_emits_a_rebind():
    src = _read("files/anatomy/wing/app/AgentKit/Runner.php")
    start = src.index("private function serveFallback(")
    body = src[start:src.index("\n\tprivate function ", start + 1)]
    emit = body[body.index(f"type: '{TYPE}'"):]
    emit = emit[:emit.index(");")]
    for key in PAYLOAD:
        assert f"'{key}' =>" in emit, f"rebind payload lacks {key}"
    assert "'by' => 'fallback'" in emit
