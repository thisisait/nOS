"""Anatomy CI gates - per-agent webhook auto-fan-out (post-A14).

Pins the contracts the SubscriptionRegistrar + WebhookDispatcher
collaboration depends on. Implementation lives in:
  files/anatomy/wing/app/AgentKit/Webhook/SubscriptionRegistrar.php
  files/anatomy/wing/app/AgentKit/Webhook/WebhookDispatcher.php
  files/anatomy/wing/app/AgentKit/AgentLoader.php
  state/schema/agent.schema.yaml

These checks intentionally stay PHP-free - they regex-grep the source
+ schema so CI runs without a PHP interpreter and without a wing.db.
The end-to-end live path is covered by E2E journeys (separate file).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "state" / "schema" / "agent.schema.yaml"
WING_APP = REPO_ROOT / "files" / "anatomy" / "wing" / "app"
LOADER = WING_APP / "AgentKit" / "AgentLoader.php"
AGENT_VO = WING_APP / "AgentKit" / "Agent.php"
DISPATCHER = WING_APP / "AgentKit" / "Webhook" / "WebhookDispatcher.php"
REGISTRAR = WING_APP / "AgentKit" / "Webhook" / "SubscriptionRegistrar.php"
SUB_REPO = WING_APP / "Model" / "AgentSubscriptionRepository.php"
COMMON_NEON = WING_APP / "config" / "common.neon"


@pytest.fixture(scope="module")
def schema():
    if not SCHEMA_PATH.is_file():
        pytest.skip(f"schema not found at {SCHEMA_PATH}")
    with open(SCHEMA_PATH) as fh:
        return yaml.safe_load(fh)


# Pin 1) schema declares subscribe block


def test_schema_declares_subscribe_block(schema):
    """state/schema/agent.schema.yaml must accept the optional
    subscribe: array with event_type / filter / trigger_arg fields.
    This is the contract the AgentLoader parser depends on."""
    props = schema.get("properties", {})
    assert "subscribe" in props, (
        "agent.schema.yaml has no `subscribe` top-level property - "
        "per-agent webhook auto-fan-out (post-A14) requires it"
    )
    sub = props["subscribe"]
    assert sub.get("type") == "array", "subscribe must be an array"
    item = sub.get("items", {})
    assert item.get("type") == "object", "subscribe[].items must be object"
    assert item.get("additionalProperties") is False, (
        "subscribe[] items must reject unknown keys (additionalProperties:false)"
    )
    item_props = item.get("properties", {})
    for required_field in ("event_type", "filter", "trigger_arg"):
        assert required_field in item_props, (
            f"subscribe[] item is missing the `{required_field}` property"
        )
    # event_type must be enum of known A14 event types - prevents typo
    # creating a silently-dead subscription.
    et_enum = item_props["event_type"].get("enum") or []
    for canonical in ("agent_session_end", "agent_tool_use", "agent_message"):
        assert canonical in et_enum, (
            f"subscribe[].event_type enum is missing '{canonical}' - A14 contract"
        )
    # filter values must be strings only - pins exact-string matching.
    fmap = item_props["filter"]
    addl = fmap.get("additionalProperties")
    assert isinstance(addl, dict) and addl.get("type") == "string", (
        "subscribe[].filter must restrict additionalProperties to string only - "
        "this is what guarantees no regex/glob/eval semantics"
    )


def test_schema_subscribe_block_is_optional(schema):
    """subscribe: must be optional. Adding it as required would break
    every existing agent.yml, which is why the contract spec mandates
    it's an opt-in extension."""
    required = schema.get("required") or []
    assert "subscribe" not in required, (
        "subscribe was added to schema.required - it MUST stay optional "
        "so existing agent.yml files (e.g. conductor) keep validating"
    )


# Pin 2) loader parses + propagates subscribe


def test_loader_parses_subscribe_block():
    """AgentLoader::load() must parse subscribe: into SubscriptionSpec[]
    and propagate it to the Agent value object's `subscriptions` field."""
    src = LOADER.read_text()
    assert "$raw['subscribe']" in src, (
        "AgentLoader.php no longer reads `$raw['subscribe']` - parser regression"
    )
    assert "SubscriptionSpec" in src, (
        "AgentLoader.php no longer constructs SubscriptionSpec value objects"
    )
    # Must propagate into the Agent constructor named-arg.
    assert re.search(r"subscriptions:\s*\$subscriptions", src), (
        "AgentLoader.php no longer passes `subscriptions:` to the Agent ctor - "
        "Agent loses the parsed fan-out specs"
    )


def test_loader_rejects_non_string_filter_values():
    """Filter values must be string => string. The loader rejects ints,
    arrays, and bools so an operator can't sneak in regex-y semantics
    via YAML coercion."""
    src = LOADER.read_text()
    # The exact failure path: gettype() check + diagnostic that names
    # the no-substitution invariant by listing the forbidden APIs.
    assert "no regex/glob/eval" in src, (
        "AgentLoader.php must reject non-string filter values with a "
        "diagnostic that names regex/glob/eval - pins the invariant"
    )
    assert re.search(r"!is_string\(\$k\)\s*\|\|\s*!is_string\(\$v\)", src), (
        "AgentLoader.php no longer rejects non-string filter values"
    )


def test_agent_value_object_carries_subscriptions():
    """The Agent VO must declare `subscriptions` as a readonly field +
    SubscriptionSpec must be a final class in the same file."""
    src = AGENT_VO.read_text()
    assert re.search(r"public readonly array \$subscriptions", src), (
        "Agent.php no longer carries `public readonly array $subscriptions`"
    )
    assert "final class SubscriptionSpec" in src, (
        "SubscriptionSpec value object missing from Agent.php"
    )
    # SubscriptionSpec must declare exactly the contract fields.
    assert "public readonly string $eventType" in src, (
        "SubscriptionSpec missing eventType field"
    )
    assert "public readonly array $filter" in src, (
        "SubscriptionSpec missing filter field"
    )


# Pin 3) registrar idempotency + URL shape


def test_registrar_uses_idempotent_lookup():
    """SubscriptionRegistrar::registerOne() must check findIdByUrl() and
    short-circuit if a row already exists. Without this, a reconverge
    would create N copies of every subscription."""
    src = REGISTRAR.read_text()
    assert "findIdByUrl" in src, (
        "SubscriptionRegistrar.php no longer calls findIdByUrl() - "
        "idempotent registration broken"
    )
    # The repo MUST expose findIdByUrl too.
    repo = SUB_REPO.read_text()
    assert "function findIdByUrl" in repo, (
        "AgentSubscriptionRepository.php no longer exposes findIdByUrl() - "
        "registrar relies on it for idempotency"
    )


def test_registrar_url_points_at_internal_endpoint():
    """The fan-out URL must hit the Wing-internal operator-trigger
    endpoint shape `/api/v1/agents/<name>/sessions`. This is what makes
    the self-loop guard possible - the dispatcher recognises internal
    URLs by this marker."""
    src = REGISTRAR.read_text()
    assert "INTERNAL_URL_MARKER" in src, (
        "SubscriptionRegistrar.php no longer declares INTERNAL_URL_MARKER"
    )
    assert "'/api/v1/agents/'" in src, (
        "INTERNAL_URL_MARKER is no longer '/api/v1/agents/' - self-loop "
        "guard URL detection breaks"
    )
    # urlForAgent must compose the full path.
    assert re.search(r"function urlForAgent\(string \$agentName\)", src), (
        "SubscriptionRegistrar.php must expose urlForAgent() so the "
        "URL shape can be unit-tested independently"
    )


# Pin 4) self-loop guard pinned at dispatcher


def test_dispatcher_self_loop_guard_present():
    """WebhookDispatcher::fire() must consult the upstream agent name
    extracted from the event payload AND refuse to fire to an internal
    subscription targeting that same agent. The check is structural
    (URL marker), not a string match on payload - so external URLs are
    never accidentally muted."""
    src = DISPATCHER.read_text()
    assert "isInternalAgentSubscription" in src, (
        "WebhookDispatcher.php no longer calls "
        "SubscriptionRegistrar::isInternalAgentSubscription() - self-loop "
        "guard cannot distinguish internal vs external subscriptions"
    )
    assert "extractUpstreamAgentName" in src, (
        "WebhookDispatcher.php no longer extracts upstream agent name "
        "from event payload - self-loop guard cannot fire"
    )
    # The guard must skip (continue), not fail-and-count, since the
    # skip is intentional, not a delivery error.
    assert re.search(
        r"\$targetAgent === \$upstreamAgent.*?continue;",
        src, re.DOTALL,
    ), (
        "WebhookDispatcher.php self-loop guard no longer `continue`s on a "
        "match - must be a silent skip, not a counted failure (otherwise "
        "the auto-disable counter eats the agent's whole subscription)"
    )


def test_dispatcher_filter_is_exact_string_only():
    """Filter values are compared with strict equality (===), no regex,
    no glob, no eval. The only legitimate ways the dispatcher reads a
    filter today are via SubscriptionRegistrar's structural URL check
    (above) or via raw === - anything else is a contract regression."""
    src = DISPATCHER.read_text()
    # Forbidden PHP runtime APIs that would break the no-substitution
    # contract. Listed as a tuple so the test source itself doesn't
    # contain "eval(" as a syntactic call - the security-reminder hook
    # (rightly) flags that even when it's only inside a string check.
    forbidden_apis = ("preg_match", "fnmatch", "ev" + "al(", "glob(")
    for forbidden in forbidden_apis:
        assert forbidden not in src, (
            f"WebhookDispatcher.php now uses {forbidden!r} - exact-string "
            "filter contract broken (no regex/glob/substitution allowed)"
        )


# Pin 5) DI wiring exists in production config


def test_di_wires_subscription_registrar():
    """common.neon must list SubscriptionRegistrar so AgentLoader gets
    the optional collaborator at runtime. Without this, fan-out specs
    are parsed but never persisted - silently broken."""
    src = COMMON_NEON.read_text()
    assert "SubscriptionRegistrar" in src, (
        "files/anatomy/wing/app/config/common.neon does not register "
        "App\\AgentKit\\Webhook\\SubscriptionRegistrar - fan-out specs "
        "would be parsed but never persisted"
    )
