"""The model is decided by the agent manifest and the binding — nowhere else.

MEASURED 2026-08-29. Six pulse jobs carried `NOS_AGENT_MODEL` — haiku, sonnet,
opus — and no scheduled ceremony reached one of them. `ClaudeCliAdapter` DOES
read it (the first draft of this gate claimed otherwise and was corrected by its
own assertion), but only passes `--model` when there is NO binding: ruling 3,
because a tier alias sent to a backend that does not know it would override the
binding's own model id. Every scheduled ceremony is bound, and no Pulse job has
used the claude-CLI runner since 2026-08-28.

So `librarian:describe-taxonomy` said `haiku` in its environment and ran on the
sonnet-tier model, and the gate that stood here enforced the pin with the words
"falls to the operator default (the most expensive tier)" — a cost claim that
was false on the only path that runs. A pin nobody reads is worse than no pin:
it answers the question "what does this cost" with a number from a dead path.

WHAT DECIDES, and what this file now pins:

  `agent.yml model.primary` carries a tier word (haiku|sonnet|opus). The
  BindingResolver parses it (`BindingResolver.php` — `preg_match('/\\b(haiku|
  sonnet|opus)\\b/')`), looks it up in the backend's `model_env` table in
  `state/llm-backends.yml`, and reads the env var named there. A tier the
  backend does not map is REFUSED at resolution, which is how ruling 1 keeps
  opus-tier ceremonies off a foreign backend.

The pins are deleted. This gate refuses their return, and pins the live path.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS = REPO / "files/anatomy/agents"
REGISTRY = REPO / "state/llm-backends.yml"

#: The words BindingResolver looks for in `model.primary`.
TIERS = ("haiku", "sonnet", "opus")


def bound_agents() -> list[tuple[str, dict]]:
    out = []
    for d in sorted(AGENTS.iterdir()):
        f = d / "agent.yml"
        if not f.is_file():
            continue
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if (doc.get("model") or {}).get("backend"):
            out.append((d.name, doc))
    return out


def test_there_are_bound_agents() -> None:
    """Positive control — nothing below means anything on an empty sweep."""
    assert len(bound_agents()) >= 3


def test_no_job_carries_a_model_pin_nothing_reads() -> None:
    """The defect, refused so it cannot come back under a new name."""
    offenders = []
    for name, doc in [(d.name, yaml.safe_load((d / "agent.yml").read_text(encoding="utf-8")) or {})
                      for d in sorted(AGENTS.iterdir()) if (d / "agent.yml").is_file()]:
        for job in ((doc.get("pulse") or {}).get("jobs") or []):
            env = job.get("env") or {}
            if "NOS_AGENT_MODEL" in env:
                offenders.append(f"{name}:{job.get('name')}")
    assert not offenders, (
        f"these jobs pin NOS_AGENT_MODEL, which the bound runner does not read: "
        f"{offenders}. It decides nothing and reads like a cost guarantee. The "
        f"tier lives in agent.yml model.primary."
    )


def test_the_pin_is_inert_under_a_binding() -> None:
    """PRECISELY, because my first draft of this gate overstated it.

    `NOS_AGENT_MODEL` is NOT unread: `ClaudeCliAdapter` reads it. What makes it
    inert for every scheduled ceremony is the condition guarding that read —
    the `--model` flag is passed only when there is NO binding (ruling 3: a
    tier alias would otherwise be sent to a backend that does not know it). All
    scheduled ceremonies are bound, so none of them reaches it.

    If that guard ever goes, the pin becomes live again and deleting it was
    wrong. This asserts the guard, not the absence of a reader.
    """
    src = (REPO / "files/anatomy/wing/app/AgentKit/LLMClient/ClaudeCliAdapter.php") \
        .read_text(encoding="utf-8")
    assert "$this->binding === null" in src, (
        "the CLI adapter no longer skips --model under a binding; a per-job "
        "NOS_AGENT_MODEL would decide again, and the pins should come back"
    )


def test_every_bound_agent_declares_a_tier_its_backend_maps() -> None:
    """The live decision. A tier the backend cannot name is refused at
    resolution — better here than at 01:10."""
    spec = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    backends = spec.get("backends") or {}          # keyed by id, not a list
    bad = []
    for name, doc in bound_agents():
        model = doc["model"]
        primary, backend = str(model.get("primary", "")), model.get("backend")
        tail = primary.split("-", 1)[-1]
        found = next((t for t in TIERS if re.search(rf"\b{t}\b", tail)), None)
        if found is None:
            bad.append(f"{name}: model.primary {primary!r} carries no tier word")
            continue
        mapping = (backends.get(backend) or {}).get("model_env") or {}
        if mapping.get(found) is None:
            bad.append(
                f"{name}: tier {found!r} has no model_env on backend {backend!r} — "
                f"the binding refuses at resolution"
            )
    assert not bad, "bound agents whose tier cannot resolve:\n  " + "\n  ".join(bad)
