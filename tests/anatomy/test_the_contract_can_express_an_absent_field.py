"""An extraction schema may not require a field the document might not have.

MEASURED 2026-08-30, and the number is the argument. `ops-extract`'s schema
listed all three fields in `required`. Against `invoice-extract` — 22 documents
that all carry all three — the two local models separated cleanly:

    hermes3:8b   14/22
    qwen3:14b    22/22

Against `invoice-absent` — the same three fields, from documents where one of
them is genuinely not printed — they did not separate at all:

    hermes3:8b   2/10   invalid 6   wrong 2
    qwen3:14b    2/10   invalid 6   wrong 2

Identical, to the sample. Six of the ten were the models doing exactly what
`system.md` asks — *"if a field is genuinely absent from the input, omit it
rather than inventing a plausible value"* — and `required` rejected the answer.
**The contract, not the model, was deciding**, which is why capability stopped
showing through.

That is this estate's own rule one layer down: absence must be sayable. A
schema that cannot express "this was not in the document" forces every answer
to claim a value, and then the only models that score are the ones that invent.
The two `wrong` rows show the shape it rewards — `"invoice_no": "N/A"` and a
currency guessed from the language of the text rather than read off it.

WHAT STAYS STRICT. `properties` and the `currency` enum are untouched: a field
that IS answered must still be the right type and one of the allowed values.
Omission is legal; a wrong value is not, and an invented sentinel scores as
wrong rather than as an omission. The distinction the family exists to measure
survives the fix.

Retro-verified 2026-08-30 by putting the three names back in `required`.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = REPO / "files/anatomy/agents/ops-extract/one-shot.schema.json"
FAMILIES = REPO / "state/ops-task-families"
RUNNER = REPO / "files/anatomy/wing/bin/run-agent.php"
WING = REPO / "files/anatomy/wing"


def test_no_extraction_field_is_required() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema.get("required") == [], (
        f"ops-extract requires {schema.get('required')}. A document that does "
        "not print a field then has no representable correct answer, and the "
        "harness scores the honest omission as `invalid` — measured 2026-08-30 "
        "as two models of different capability both landing on 2/10.")


def test_undeclared_keys_are_refused() -> None:
    """THE OTHER HALF, and it was found the same afternoon by the first hosted
    run. With `required: []` and no `additionalProperties: false`, a schema
    accepts ANY object: MiniMax-M2.7 answered an invoice prompt with
    `{"business_name": "Cafe Slavia", "table_number": 7}` — sharing no key with
    the contract — and OneShot validated it. Empty `required` without this is
    not a loosened contract, it is no contract."""
    for path in (SCHEMA, SCHEMA.parent.parent / "ops-extract-cloud/one-shot.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema.get("additionalProperties") is False, (
            f"{path.parent.name}: required is empty and undeclared keys are "
            "allowed, so any object at all validates")
    # BEHAVIOUR, not the word. A first draft asserted `"additionalProperties"
    # in OneShot.php` and stayed green when the guard was deleted, because the
    # comment above it still said the word — the same prose-detector trap this
    # estate has paid for three times in a day.
    if shutil.which("php") is None or not (WING / "vendor/autoload.php").exists():
        pytest.skip("php or the wing vendor tree is absent")
    cases = {
        "invented keys": ('{"business_name":"Cafe Slavia","table_number":7}', False),
        "honest omission": ('{"invoice_no":"FV-1"}', True),
        "empty object": ("{}", True),
        "wrong currency": ('{"currency":"USD"}', False),
        "total as string": ('{"total":"1240"}', False),
        "full correct": ('{"invoice_no":"A","total":1,"currency":"EUR"}', True),
    }
    php = """
require __DIR__ . '/vendor/autoload.php';
$m = new ReflectionMethod(App\\AgentKit\\OneShot::class, 'check');
$schema = json_decode(file_get_contents($argv[1]), true);
$out = [];
foreach (json_decode($argv[2], true) as $label => $raw) {
    $chain = null;
    $out[$label] = $m->invokeArgs(null, [$raw, $schema, &$chain]) === null;
}
echo json_encode($out);
"""
    done = subprocess.run(
        ["php", "-r", php, str(SCHEMA), json.dumps({k: v[0] for k, v in cases.items()})],
        capture_output=True, text=True, timeout=60, cwd=WING)
    assert done.returncode == 0, done.stderr[-400:]
    got = json.loads(done.stdout)
    for label, (_raw, want_accepted) in cases.items():
        assert got[label] is want_accepted, (
            f"{label}: schema {'refused' if want_accepted else 'ACCEPTED'} it; "
            f"expected {'accepted' if want_accepted else 'refused'}")


def test_the_answer_shape_is_still_constrained() -> None:
    """Dropping `required` must not become dropping the contract. A field that
    IS answered still has to be the right type and value."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    props = schema.get("properties") or {}
    assert set(props) == {"invoice_no", "total", "currency"}
    assert props["total"]["type"] == "number", "a total as a string would pass"
    assert props["currency"].get("enum") == ["EUR", "CZK"], (
        "the currency enum is gone — an invented currency would validate")


def test_the_absence_family_exists_and_labels_omissions() -> None:
    """The family is what turns the rule into a measurement. Without at least
    one sample whose label omits a field, `required: []` is untested slack."""
    samples = [json.loads(line) for line
               in (FAMILIES / "invoice-absent/samples.jsonl").read_text(
                   encoding="utf-8").splitlines() if line.strip()]
    assert len(samples) >= 8, f"only {len(samples)} absence samples"
    partial = [s for s in samples if len(s["expect"]) < 3]
    assert len(partial) >= 6, (
        f"only {len(partial)} samples label a MISSING field; the family stops "
        "measuring invention and becomes a second extraction set")
    assert any(s["expect"] == {} for s in samples), (
        "no sample where nothing is extractable — the strongest case, and the "
        "one where a model most wants to fill the object in")


def test_an_empty_answer_matches_an_empty_label() -> None:
    """PHP's `json_decode` returns `[]` for both `{}` and `[]`, so the honest
    "nothing is extractable here" arrives at the oracle as a LIST and never
    equals the label's dict. Measured 2026-08-30: all three subjects — 8B, 14B
    and the hosted model — lost the same two samples (a04, a08) to it, which is
    the signature of an oracle bug rather than a capability difference.

    Behavioural, through `score()` with a stub runner: a source assertion here
    would be the prose-detector trap this file already carries one scar from."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "ops_harness", REPO / "tools/nos-ops-harness.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    stub = REPO / "tests/anatomy/_stub_empty_runner.sh"
    got = mod.score(
        binding={"backend": "stub", "model": "stub", "size_b": 0, "model_env": None},
        samples=[{"id": "empty", "input": "x", "expect": {}},
                 {"id": "full", "input": "x", "expect": {"invoice_no": "A"}}],
        meta={}, agent="ops-extract", cmd=["sh", str(stub)], timeout=30)
    assert got["exact"] == 1 and got["wrong_labels"] == 1, (
        f"an empty chain scored {got['exact']} exact / {got['wrong_labels']} "
        "wrong against one empty and one non-empty label; expected 1/1. If "
        "exact is 0 the harness is measuring the JSON encoding, not the model; "
        "if wrong is 0 an empty answer now passes for documents that DO carry "
        "fields, which is worse.")


def test_a_refused_answer_says_why() -> None:
    """`chain: null, error: null` cannot distinguish 'omitted a required field'
    from 'answered in prose', and those call for opposite fixes. OneShot has
    always returned the reason; the summary used to drop it."""
    src = RUNNER.read_text(encoding="utf-8")
    assert "'chain_error' =>" in src, (
        "the runner summary no longer carries the schema's reason, so a "
        "harness records `detail: null` for every rejection")
