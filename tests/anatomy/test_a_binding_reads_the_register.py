"""A backend binding must agree with the register that declares its transfer.

WHY THIS GATE READS VALUES. `gdpr-agent-processors` (57168ff8) made the
Article-30 register say, per agent, which processor its ceremony ships prompts
to. The binding layer (`model.backend` in agent.yml → state/llm-backends.yml →
App\\AgentKit\\BindingResolver) is the machinery that could make that register
FALSE again five minutes after it became true: route curator to MiniMax while
its gdpr block names only Anthropic, and the register is complete, well-formed
— and wrong. A routing decision that disagrees with the register is a
compliance defect, not a bug (coordinator ruling, 2026-08-13), so the register
is the INPUT to routing, never a parallel document.

THE SIX GATES are prose in state/llm-backends.yml and code in BindingResolver;
this file holds the DECLARED DATA to the four that are decidable offline:

  * a declared backend exists in the registry            (gate 2)
  * the agent's own gdpr.processors names the backend's
    processor — the match key, not a vibe                (gate 4)
  * a deferred agent declares no binding at all — inspektor's
    `processors: []` is truthful ONLY while it never runs; its own
    record says "THIS RECORD MUST BE REWRITTEN BEFORE THE AGENT IS
    ARMED", and a binding is an arming                   (gate 5)
  * an opus-pinned ceremony declares no foreign binding — ruling 1
    keeps code-authoring ceremonies (migration-author and
    upgrade-architect pin NOS_AGENT_MODEL: "opus") on the default
    backend until the inner posture is tightened          (gate 6)

Gates 1 and 3 (arming via NOS_ARMED_BACKENDS, refusal semantics) are runtime
behaviour and belong to the resolver's own gate.

ANTI-VACUITY: the sweep must FIND the agents — nine directories exist today —
and the registry must parse to at least the default backend, or every check
above passes by absence. Both are asserted as positive controls.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
REGISTRY = REPO / "state/llm-backends.yml"
AGENTS = REPO / "files/anatomy/agents"
SECRETS_TPL = REPO / "templates/secrets.yml.j2"


def _registry() -> dict:
    doc = yaml.safe_load(REGISTRY.read_text())
    assert isinstance(doc, dict) and isinstance(doc.get("backends"), dict), (
        "state/llm-backends.yml no longer parses to a backends map"
    )
    return doc["backends"]


def _agents() -> list[tuple[str, dict]]:
    out = []
    for d in sorted(AGENTS.iterdir()):
        f = d / "agent.yml"
        if d.is_dir() and f.is_file():
            out.append((d.name, yaml.safe_load(f.read_text()) or {}))
    assert len(out) >= 9, (
        f"the agent sweep found {len(out)} agent.yml files where nine exist — "
        "every value check below would pass by absence"
    )
    return out


def _ceremony_pins_opus(name: str) -> bool:
    flat = AGENTS / f"{name}.yml"
    return flat.is_file() and 'NOS_AGENT_MODEL: "opus"' in flat.read_text()


def test_the_registry_is_well_formed_and_fail_closed():
    backends = _registry()
    defaults = [n for n, b in backends.items() if (b or {}).get("default")]
    assert defaults == ["anthropic"], (
        f"exactly one default backend (anthropic) must exist, found {defaults} — "
        "two defaults is a coin toss and zero is a crash on every unbound agent"
    )
    secrets_tpl = SECRETS_TPL.read_text()
    for name, b in backends.items():
        if (b or {}).get("default"):
            continue
        assert b.get("base_url", "").startswith("https://"), (
            f"backend {name!r} has no https base_url — an env override pointing "
            "nowhere, or somewhere unencrypted"
        )
        ref = b.get("auth_secret", "")
        assert ref.startswith(("nos:", "env:", "infisical:")), (
            f"backend {name!r} auth_secret {ref!r} is not a secret_ref — the "
            "registry must carry a POINTER, never a value (AgentKit's "
            "secret_ref rule, and the reason wing.db never held a key)"
        )
        if ref.startswith("nos:"):
            key = ref.split(":", 1)[1]
            assert f"{key}:" in secrets_tpl, (
                f"backend {name!r} resolves `nos:{key}` but templates/"
                "secrets.yml.j2 never persists that key — the binding would "
                "arm and then fail at session open with no secret to resolve"
            )
        tiers = b.get("model_env")
        assert isinstance(tiers, dict) and set(tiers) == {"haiku", "sonnet", "opus"}, (
            f"backend {name!r} must map exactly the three tiers the agents pin"
        )
        assert tiers["opus"] is None, (
            f"backend {name!r} maps the opus tier to {tiers['opus']!r}. "
            "Ruling 1 keeps opus-pinned (code-authoring) ceremonies on the "
            "default backend until the inner posture is tightened — the "
            "registry expresses that as opus: null, and the resolver refuses."
        )
        assert b.get("processor_match"), (
            f"backend {name!r} has no processor_match — the binding↔register "
            "agreement check would have no key and pass everything"
        )


def test_a_declared_binding_agrees_with_the_agents_register_entry():
    backends = _registry()
    problems = []
    declared = 0
    for name, doc in _agents():
        backend_name = ((doc.get("model") or {}).get("backend"))
        if backend_name is None:
            continue
        declared += 1
        if backend_name not in backends:
            problems.append(f"{name}: backend {backend_name!r} not in the registry")
            continue
        spec = backends[backend_name] or {}
        if spec.get("default"):
            continue  # the default backend is what the register already covers
        status = ((doc.get("metadata") or {}).get("runner_status", "")).lower()
        if status == "deferred":
            problems.append(
                f"{name}: declares backend {backend_name!r} while "
                "runner_status=deferred — its register entry (processors: []) "
                "is truthful only because it never runs; a binding is an arming "
                "and makes that record the estate's old false assertion"
            )
        if _ceremony_pins_opus(name):
            problems.append(
                f"{name}: declares backend {backend_name!r} while its ceremony "
                'pins NOS_AGENT_MODEL: "opus" — ruling 1 keeps code-authoring '
                "ceremonies on the default backend"
            )
        match = spec.get("processor_match", "")
        processors = (doc.get("gdpr") or {}).get("processors") or []
        names = [str((p or {}).get("name", "")) for p in processors]
        if not any(match in n for n in names):
            problems.append(
                f"{name}: routes to {backend_name!r} but its gdpr.processors "
                f"{names} never names {match!r} — the Article-30 register "
                "would be complete, well-formed, and false. Write the "
                "processor entry first; the binding reads the register, it "
                "does not outrun it."
            )
    assert not problems, "\n  " + "\n  ".join(problems)
    # No agent declares a binding today (MiniMax is prepared, not armed) — the
    # loop above must still be REAL. Prove it by running the same checks on a
    # synthetic offender and requiring them to object.
    if declared == 0:
        fake = {
            "model": {"backend": "minimax"},
            "metadata": {"runner_status": "deferred"},
            "gdpr": {"processors": [{"name": "Anthropic, PBC"}]},
        }
        objections = []
        spec = backends["minimax"]
        if ((fake.get("metadata") or {}).get("runner_status")) == "deferred":
            objections.append("deferred")
        if not any(
            spec["processor_match"] in str((p or {}).get("name", ""))
            for p in fake["gdpr"]["processors"]
        ):
            objections.append("processor-missing")
        assert objections == ["deferred", "processor-missing"], (
            "the positive control stopped objecting — the checks above have "
            "gone vacuous and a real binding would sail through them"
        )
