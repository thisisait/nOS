"""The loop's HTTP wire, exercised — because nothing had ever called through it.

An opposition review on 2026-08-03 (five Fable agents) found the engine's
defensive half genuinely built — three-valued verdicts, WORM rows, a SQLite
authorizer, no endpoint that accepts a verdict — and its PRODUCTIVE half unable
to run at all. Four defects, all of one kind:

  1. `looproutes` opened the ledger as "agent:proposer" / "engine:evaluator",
     the estate's actor_id spellings. `ledger._ROLE_WRITES` is keyed on the bare
     role, so every call raised KeyError: POST /proposals, GET /history and
     POST /judge answered 500. The wire had never carried a proposal.
  2. GET /budget read `b.denied` and `b.oracle_paths`. A `Budget` has
     `forbidden` and `oracle_rules()` — AttributeError on every call — while
     `Budget.to_dict()`, the serializer budget.py defines AND tests, sat unused
     beside the broken hand-rolled copy.
  3. The plugin's judge skill documents `{"proposal": "<uuid>"}`; the engine
     names it `proposal_uuid`. Pydantic's default DROPS unknown keys, so that
     call returned 202, ran the set as an unattached baseline, sealed a verdict
     against nothing, and left the proposal with zero verdicts — which the
     ledger reads as `attempt-pending` and refuses forever. One
     documented-as-correct call both fabricated an attributed pass and wedged
     the fingerprint permanently, with `forget()` having no route to lift it.
  4. `sweep_crashed()` — promised in two docstrings as what reconciles a killed
     run — had no caller. A run killed mid-subprocess stayed 'running' forever.

WHAT LINKS THEM, and it is the estate's recurring shape: EVERY ONE lives on a
path no test reaches. The loop's suite is large and good, and it tests judges,
ledger and budget as pure Python — each with its arguments supplied by the test.
The wire is where those arguments come from, and it was the one part with no
harness. `tests/anatomy/` had no `test_loop_routes*` at all.

So this file tests the SEAM, never the modules on either side of it. It imports
the route module the way Bone does and asserts the contract holds in both
directions: what the routes pass down, and what the documented clients send up.
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"
PLUGIN = REPO / ".claude/plugins/nos-loop"


@pytest.fixture(scope="module")
def wire():
    """Import the route module the way Bone does — flat, bone dir on the path."""
    sys.path.insert(0, str(BONE))
    try:
        yield {
            "routes": importlib.import_module("looproutes"),
            "ledger": importlib.import_module("ledger"),
            "budget": importlib.import_module("budget"),
        }
    finally:
        sys.path.remove(str(BONE))


def test_the_routes_open_the_ledger_under_a_role_it_recognises(wire):
    """Defect 1. A role the authorizer does not know is a KeyError, not a 403."""
    known = set(wire["ledger"]._ROLE_WRITES)
    src = (BONE / "looproutes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    passed: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and ast.unparse(node.func).endswith("open_ledger")):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                passed.add(arg.value)          # a literal role
            elif isinstance(arg, ast.Name):
                # a module constant — resolve it off the imported module
                value = getattr(wire["routes"], arg.id, None)
                if isinstance(value, str):
                    passed.add(value)
    assert passed, "no open_ledger call found — this gate has stopped watching anything"
    unknown = passed - known
    assert not unknown, (
        f"the routes open the ledger as {sorted(unknown)}, which the authorizer "
        f"does not know ({sorted(known)}). That is a KeyError, so the route "
        f"answers 500 — the shape that left the wire dead from the day it shipped."
    )


def test_the_budget_route_serialises_with_the_serializer_that_exists(wire):
    """Defect 2. Two serializers, one tested, and the route used the other."""
    src = (BONE / "looproutes.py").read_text(encoding="utf-8")
    fn = src[src.index("def get_budget"):]
    fn = fn[: fn.index("\n@router")]
    assert "to_dict()" in fn, (
        "GET /budget hand-rolls its serialization again. budget.Budget.to_dict "
        "exists and is tested; the hand-rolled copy named two attributes the "
        "dataclass does not have and raised AttributeError on every call."
    )
    fields = {f.name for f in wire["budget"].Budget.__dataclass_fields__.values()}
    for ghost in ("denied", "oracle_paths"):
        assert ghost not in fields, (
            f"`{ghost}` is now a real Budget field — this test's premise moved; "
            f"re-read the route before trusting it"
        )


def test_both_request_bodies_refuse_a_field_they_do_not_know(wire):
    """Defect 3, closed at the class rather than the instance.

    A misspelt field must be a 422. Dropping it silently turns one operation
    into a different one while returning success — which is how a verdict came
    to be sealed against no proposal at all.
    """
    for name in ("ProposalIn", "JudgeIn"):
        model = getattr(wire["routes"], name)
        assert model.model_config.get("extra") == "forbid", (
            f"{name} still accepts unknown fields silently. The plugin's judge "
            f"skill sent `proposal` where the engine reads `proposal_uuid`, and "
            f"the run executed UNATTACHED while reporting 202."
        )


def _fenced_json_bodies(path: Path) -> list[tuple[int, dict]]:
    """Every JSON object literal in a fenced block, with its line number."""
    out: list[tuple[int, dict]] = []
    text = path.read_text(encoding="utf-8")
    for m in re.finditer(r"(\{[^{}]*\})", text):
        blob = m.group(1)
        if '"' not in blob:
            continue
        line = text[: m.start()].count("\n") + 1
        # Placeholders like <uuid> / <set> are not JSON; make them strings so a
        # documented SHAPE can be validated even where the value is illustrative.
        candidate = re.sub(r"<[^>\"]*>", "PLACEHOLDER", blob)
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict) and parsed:
            out.append((line, parsed))
    return out


@pytest.mark.parametrize(
    "skill, model_name, required_hint",
    [
        ("skills/propose/SKILL.md", "ProposalIn", "weakness_id"),
        ("skills/judge/SKILL.md", "JudgeIn", "gate_set"),
    ],
)
def test_the_documented_request_bodies_validate_against_the_models(
    wire, skill, model_name, required_hint
):
    """Defect 3's origin: the plugin documents bodies the engine rejects.

    This is the gate that would have caught it. `test_loop_plugin_is_thin.py`
    lints the plugin's PROSE for restated decisions — valuable, and blind to
    whether the requests it shows can be sent at all. Here the fenced bodies are
    fed to the real pydantic models.

    A body is only checked if it looks like a request for THIS endpoint (it
    mentions a required field), so response examples and unrelated snippets do
    not produce false failures.
    """
    path = PLUGIN / skill
    if not path.is_file():
        pytest.skip(f"{skill} not present")
    model = getattr(wire["routes"], model_name)
    bodies = [(ln, b) for ln, b in _fenced_json_bodies(path) if required_hint in b]
    assert bodies, (
        f"no documented request body found in {skill} — either the skill stopped "
        f"showing the call, or this extractor stopped seeing it. Both are worth "
        f"knowing; neither should read as a pass."
    )
    for line, body in bodies:
        try:
            model.model_validate(body)
        except Exception as exc:
            pytest.fail(
                f"{skill}:{line} documents a body the engine REJECTS.\n"
                f"  body:  {json.dumps(body, sort_keys=True)}\n"
                f"  error: {exc}\n"
                f"A model following this skill cannot complete a turn, and with "
                f"extra='forbid' it now gets a 422 instead of a silent no-op."
            )


def test_the_boot_sweep_has_a_caller(wire):
    """Defect 4. A reconciliation nothing invokes is a docstring."""
    main_src = (BONE / "main.py").read_text(encoding="utf-8")
    assert "sweep_crashed()" in main_src, (
        "nothing calls sweep_crashed() at boot. A run killed mid-subprocess "
        "then stays status='running' forever and never aggregates to "
        "INDETERMINATE — the row reads as neither passed nor failed, and the "
        "fingerprint that depends on it wedges as attempt-pending."
    )
