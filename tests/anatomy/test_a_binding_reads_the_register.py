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
        # Every row — default included — carries the two facts other layers
        # key on: the wire protocol (resolver gate 7 pairs adapters with it)
        # and the residency boolean (the compliance rule below reads it).
        assert (b or {}).get("protocol") in {"anthropic", "openai"}, (
            f"backend {name!r} protocol {b.get('protocol')!r} is not a "
            "protocol an adapter speaks — gate 7 would refuse every binding "
            "to it, or worse, a typo would read as a new protocol"
        )
        residency = (b or {}).get("residency") or {}
        assert isinstance(residency.get("eu"), bool), (
            f"backend {name!r} declares no residency.eu boolean — the "
            "EU-residency compliance rule has nothing to read and every "
            "agent's transfers_outside_eu claim goes ungated"
        )
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


def test_every_backend_ships_prepared_not_armed():
    """Derived from the registry, so the NEXT row is covered the day it lands.

    The prepared-not-armed contract, generalised from the minimax original
    when mistral-eu became the second row (2026-08-16): every non-default
    backend's enabled_flag defaults FALSE in default.config.yml (arming is a
    config.yml act, never a committed default), the wing plist renders the
    backend's name into NOS_ARMED_BACKENDS conditioned on exactly that flag,
    and every model_env the tiers point at is rendered there too — an armed
    backend whose tier env nobody renders refuses every session with "armed
    without a model id", which is the resolver working but the converge's
    fault. A backend-shaped hole in any of the three layers is found here,
    not on the night.
    """
    cfg = yaml.safe_load((REPO / "default.config.yml").read_text())
    plist = (REPO / "roles/pazny.wing/templates/wing.plist.j2").read_text()
    problems = []
    for name, b in _registry().items():
        if (b or {}).get("default"):
            continue
        flag = (b or {}).get("enabled_flag", "")
        if cfg.get(flag) is not False:
            problems.append(
                f"{name}: {flag or '(no enabled_flag)'} must exist and "
                f"default false in default.config.yml, found {cfg.get(flag)!r}"
            )
        # Prefix-quoted, not exact-quoted: the template legally renders
        # `'minimax '` with a joining space inside the literal.
        if f"'{name}" not in plist or flag not in plist:
            problems.append(
                f"{name}: wing.plist.j2 does not render this backend into "
                f"NOS_ARMED_BACKENDS from {flag} — the flag would arm nothing"
            )
        for tier, env in ((b or {}).get("model_env") or {}).items():
            if env is not None and f"<key>{env}</key>" not in plist:
                problems.append(
                    f"{name}: tier {tier} reads {env}, which wing.plist.j2 "
                    "never renders — armed sessions refuse with 'armed "
                    "without a model id' and the night blames the resolver"
                )
    assert not problems, "\n  " + "\n  ".join(problems)


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
        # RESIDENCY TRUTH (2026-08-16, the operator's EU question). The
        # serving set of a bound agent is the declared backend AND the
        # default it degrades to when disarmed — a run can land on either,
        # so the Article-30 record must be true of BOTH. Only when every
        # member is EU-resident may the record say the data stays. Today no
        # EU backend exists, so this asserts every bound agent says
        # `transfers_outside_eu: true` — and the day a Mistral row lands,
        # the same rule says exactly which agents may flip to `false`:
        # those whose WHOLE serving set went EU, not those whose declared
        # half did.
        serving = [spec, backends.get("anthropic") or {}]
        any_non_eu = any(
            not ((s.get("residency") or {}).get("eu", False)) for s in serving
        )
        gdpr = doc.get("gdpr") or {}
        if any_non_eu and gdpr.get("transfers_outside_eu") is not True:
            problems.append(
                f"{name}: bound to {backend_name!r} whose serving set "
                "includes a non-EU backend, but its register entry does not "
                "declare transfers_outside_eu: true — the record is false "
                "the moment the binding disarms, if not sooner"
            )
        if any_non_eu and gdpr.get("eu_residency") is not False:
            problems.append(
                f"{name}: eu_residency must be false while any backend in "
                "its serving set is non-EU"
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
