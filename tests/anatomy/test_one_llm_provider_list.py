"""Anatomy gate: the LLM provider list is declared once, and adapters come first.

MEASURED 2026-08-10. The alternation `(anthropic|openclaw|openai|local)` — the
membership as it stood that morning — was restated SIX times across four
languages, with nothing comparing them:

    files/anatomy/wing/app/AgentKit/AgentLoader.php             preg_match
    state/schema/agent.schema.yaml                              three `pattern:`
    tests/anatomy/test_agentkit_naming.py                       a regex literal
    files/anatomy/cortex/server/cortex-opcodes.ts               MODEL_URI_RE

The sixth was written the day BEFORE this gate, and it already disagreed with
the other five on the tail. That is how fast a restated law drifts.

WHAT THE DRIFT COST, because it was not cosmetic. The old tail `[a-z0-9.-]+`
forbids a colon, and every real ollama tag has one — `qwen2.5-coder:32b`,
`nomic-embed-text:latest`, `hermes3:8b` on this host. The correct value was
therefore UNWRITEABLE, so it was dash-ified into `openclaw-qwen-coder-32b`,
which resolves (OpenClawAdapter.php:40 strips the prefix) to `qwen-coder-32b` —
a model that does not exist, declared as the fallback of all nine agents. The
fallback is live code (Runner.php:656, on a transient primary failure), so it
would have been discovered at the exact moment resilience was needed.

THE ORDERING RULE, inherited verbatim from opcodes → handlers. Wing refuses to
boot when KEAP publishes an opcode no handler covers; the same shape applies
here. A provider in the enum with no adapter in `Factory::fromUri` is validation
outrunning capability: the schema accepts the URI and the factory throws. So the
ADAPTER ships first and the enum second, and `test_every_declared_provider_has_an_adapter`
is what makes that ordering real rather than remembered.

That rule caught something on its first run, which is why the enum reads
`(anthropic|openclaw)` today: `openai` and `local` were in the list and
`Factory::fromUri` has no arm for either — its own docstring calls them
"reserved (not yet implemented; throws)". An agent.yml naming `openai-gpt-4`
therefore passed every schema check in the estate and failed at session-open.
Reserved belongs in the CODE, where the Factory already says so, not in the
vocabulary a validator accepts. Nothing used either, so narrowing cost nothing.

WHAT THIS CANNOT COVER. Whether an adapter WORKS, or whether the provider is
reachable. Only that the estate agrees on which names are legal.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
GENOME = REPO / "state/genome/entity.schema.json"
GENERATED_PY = REPO / "files/anatomy/module_utils/nos_entity.py"

AGENT_SCHEMA = REPO / "state/schema/agent.schema.yaml"
AGENT_LOADER = REPO / "files/anatomy/wing/app/AgentKit/AgentLoader.php"
FACTORY = REPO / "files/anatomy/wing/app/AgentKit/LLMClient/Factory.php"
NAMING_GATE = REPO / "tests/anatomy/test_agentkit_naming.py"
CORTEX_OPCODES = REPO / "files/anatomy/cortex/server/cortex-opcodes.ts"
AGENT_DIR = REPO / "files/anatomy/agents"

#: The WHOLE model-uri regex, not just its alternation. An earlier draft matched
#: only `(a|b|c)` and would have passed a copy whose TAIL had drifted — which is
#: the half that actually broke: the alternation agreed in all six places while
#: the tail did not, and it was the tail that made the right model name
#: unspellable. Anchors are excluded from the capture because a YAML `pattern:`,
#: a PHP `preg_match` and a JS literal delimit them differently.
URI_PATTERN = re.compile(
    r"\^\((?:anthropic|openclaw)(?:\|[a-z0-9_]+)*\)-\[[^\]]+\](?:\{\d+,\d+\}|\+|\*)\$"
)


def _generated():
    spec = importlib.util.spec_from_file_location("nos_entity_under_test", GENERATED_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _generated()


def test_the_genome_is_the_source_and_the_artifact_is_current(gen) -> None:
    """Guard the guard: a stale artifact would make every comparison below agree
    with a fact nobody holds any more."""
    import json

    schema = json.loads(GENOME.read_text(encoding="utf-8"))
    # `vocabularies`, not `definitions`: a facet is something an ENTITY
    # carries, and no nOS service has an `llm` block. The genome contract
    # gate refused it as a facet on the first run and was right to.
    declared = schema["vocabularies"]["llm"]["properties"]["provider"]["enum"]
    assert list(gen.LLM_PROVIDERS) == declared, (
        "files/anatomy/module_utils/nos_entity.py is stale against the genome — "
        "run `python3 tools/genome-codegen.py`."
    )
    tail = schema["vocabularies"]["llm"]["properties"]["model_id_pattern"]["const"]
    assert gen.MODEL_URI_PATTERN == "^(" + "|".join(declared) + ")-" + tail + "$"


def test_the_tail_admits_a_real_model_tag(gen) -> None:
    """The defect in one assertion. These are `ollama list` on this host."""
    for tag in ("qwen2.5-coder:32b", "nomic-embed-text:latest", "hermes3:8b", "qwen3:14b"):
        assert gen.MODEL_URI_RE.match(f"openclaw-{tag}"), (
            f"`openclaw-{tag}` is not a legal model uri, so the correct value cannot "
            "be written down. That is what produced `qwen-coder-32b` — an approximation "
            "of a name the vocabulary would not accept."
        )


def test_the_tail_is_still_bounded(gen) -> None:
    """Permissive is not unbounded; a model id is not a free text field."""
    assert not gen.MODEL_URI_RE.match("openclaw-" + "x" * 97)
    assert not gen.MODEL_URI_RE.match("openclaw-has spaces")
    assert not gen.MODEL_URI_RE.match("openclaw-")
    assert not gen.MODEL_URI_RE.match("mistral-large"), "unknown provider must not match"
    # `claude-opus-4-7` stood here as the bare-model example until 2026-08-11,
    # when `claude` became a real provider (the local CLI). It is now a LEGAL
    # uri meaning "the CLI running opus-4-7", which is the honest reading of
    # that string on this estate — so the example moved to one that is still
    # genuinely bare. Worth recording rather than silently swapping: adding a
    # provider changes what previously-invalid strings MEAN, and the day that
    # happens is the day to check nothing was relying on the refusal.
    assert not gen.MODEL_URI_RE.match("opus-4-7"), "a bare model with no provider"
    assert not gen.MODEL_URI_RE.match("qwen2.5-coder:32b"), "a bare ollama tag is not a uri"


# ── the hand-written copies ────────────────────────────────────────────────


#: Where a restated copy could live. A REPO SWEEP, not a hand-listed set — the
#: first draft of this gate listed four files and missed a SEVENTH copy in
#: tests/anatomy/test_agent_schema.py, discovered only because widening the tail
#: made that file fail. A hand-maintained list of the places a law is repeated is
#: itself one more place to remember, which is the defect, not the fix.
SEARCH_ROOTS = ("state", "files/anatomy", "tests/anatomy", "roles", "tasks", "tools")
SEARCH_SUFFIXES = {".py", ".php", ".ts", ".yml", ".yaml", ".json", ".j2"}
SEARCH_SKIP = ("node_modules", "/vendor/", "/dist/", "/.svelte-kit/")


def _copies() -> list[tuple[pathlib.Path, str]]:
    out: list[tuple[pathlib.Path, str]] = []
    for root in SEARCH_ROOTS:
        base = REPO / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix not in SEARCH_SUFFIXES or not path.is_file():
                continue
            if any(skip in str(path) for skip in SEARCH_SKIP):
                continue
            # The generated artifact IS the genome's voice; comparing it to
            # itself would be the tautology this suite exists to avoid.
            if path == GENERATED_PY:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for match in URI_PATTERN.finditer(text):
                out.append((path, match.group(0)))
    return out


def test_every_hand_written_copy_matches_the_genome(gen) -> None:
    canonical = gen.MODEL_URI_PATTERN
    copies = _copies()
    assert copies, (
        "no provider alternation found anywhere — either the estate stopped "
        "restating it (delete this test) or the search went blind (fix it)."
    )
    drifted = [(p, found) for p, found in copies if found != canonical]
    assert not drifted, (
        "a hand-written copy of the model-uri rule disagrees with the genome:\n"
        f"    genome: {canonical}\n"
        "These cannot be generated in place — a JSON-schema `pattern:`, a PHP "
        "preg_match and a vendored TS regex each live inside a file with its own "
        "authorship — so this gate is the diff:\n  "
        + "\n  ".join(f"{p.relative_to(REPO)}: {found}" for p, found in drifted)
    )


def test_every_declared_provider_has_an_adapter(gen) -> None:
    """Adapter first, enum second. The opcode/handler rule, one layer over."""
    factory = FACTORY.read_text(encoding="utf-8")
    arms = set(re.findall(r"^\s*'([a-z0-9_]+)'\s*=>", factory, re.M))
    missing = [p for p in gen.LLM_PROVIDERS if p not in arms]
    assert not missing, (
        f"the genome declares provider(s) with no adapter in Factory::fromUri: {missing}. "
        "The schema would accept the URI and the factory would throw on it — validation "
        "outrunning capability. Ship the adapter first, then add the provider."
    )


def test_no_agent_names_a_model_the_estate_cannot_serve(gen) -> None:
    """Every agent.yml model uri must at least be SPELLABLE under the genome.

    Not that the model is installed — that is a runtime fact and this suite is
    offline. But `openclaw-qwen-coder-32b` was legal under the old pattern and
    wrong under any reading, so shape is where the check belongs.
    """
    offenders: list[str] = []
    for agent_yml in sorted(AGENT_DIR.glob("*/agent.yml")):
        raw = yaml.safe_load(agent_yml.read_text(encoding="utf-8")) or {}
        for slot in ("primary", "fallback"):
            uri = (raw.get("model") or {}).get(slot)
            if uri and not gen.MODEL_URI_RE.match(str(uri)):
                offenders.append(f"{agent_yml.relative_to(REPO)} {slot}={uri}")
    assert not offenders, "agent model uri does not match the genome:\n  " + "\n  ".join(offenders)
