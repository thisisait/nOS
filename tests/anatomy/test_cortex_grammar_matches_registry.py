"""`state/cortex-lang.gbnf` is a SECOND copy of the opcode registry, so it rots.

WHY THIS GATE EXISTS. The grammar constrains a local model to emit only
well-shaped cortex-lang, and it does that by hard-coding what `cortex-opcodes.ts`
declares: the 15 opcode names, and per opcode both the operand arity and the
namespaces that opcode accepts. Two representations of one fact, which is the
shape this estate has paid for repeatedly — the version pin declared twice, the
`when` column split across two writers, the anatomy graph and its vendored copy.

The failure is quiet in the dangerous direction. Add an opcode to the registry
and the grammar simply cannot produce it: constrained decoding will steer the
model away from a verb the validator would have accepted, and the bench will
report a capability gap that is really a stale file. Nothing errors.

WHAT THIS DOES NOT CHECK, because the grammar deliberately does not encode it:
param names and types, CORTEX_LIMITS other than `stages`, and whether a dotted
id resolves. Those stay `POST /agent/v1/validate`'s job — see the grammar's own
header for why that division is the point rather than a shortfall.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GRAMMAR = REPO / "state/cortex-lang.gbnf"
REGISTRY = REPO / "files/anatomy/cortex/server/cortex-opcodes.ts"

#: `name: 'map', … operands: { min: 1, max: 1, namespaces: ['tax','ent','kg'] }`
_OPCODE_RE = re.compile(
    r"name: '([a-z][a-z0-9-]*)',.*?"
    r"operands: \{ min: (\d+), max: (\d+), namespaces: \[([^\]]*)\] \}",
    re.S,
)


def _registry() -> dict[str, tuple[int, int, list[str]]]:
    src = REGISTRY.read_text(encoding="utf-8")
    block = src[src.index("export const CORTEX_OPCODES") :]
    out: dict[str, tuple[int, int, list[str]]] = {}
    for name, lo, hi, namespaces in _OPCODE_RE.findall(block):
        out[name] = (
            int(lo),
            int(hi),
            [n.strip().strip("'") for n in namespaces.split(",") if n.strip()],
        )
    return out


def _rules() -> dict[str, str]:
    """Rule name -> its right-hand side, comments and blank lines dropped."""
    rules: dict[str, str] = {}
    for line in GRAMMAR.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "::=" not in line:
            continue
        lhs, _, rhs = line.partition("::=")
        rules[lhs.strip()] = rhs.strip()
    return rules


def _namespaces_of(rhs: str) -> list[str]:
    """The quoted alternatives LEFT of the `":"` separator.

    `e-get ::= ("tax" | "kg" | "db" | "svc" | "doc") ":" operand` — a naive
    scan for quoted tokens also returns the separator, which is how the first
    version of this gate failed against a correct grammar.
    """
    head, sep, _tail = rhs.partition('":"')
    assert sep, f"operand rule has no namespace separator: {rhs!r}"
    return re.findall(r'"([^"\\]+)"', head)


@pytest.fixture(scope="module")
def registry() -> dict[str, tuple[int, int, list[str]]]:
    assert REGISTRY.exists(), f"no opcode registry at {REGISTRY}"
    reg = _registry()
    assert reg, "parsed no opcodes out of the registry — did its shape change?"
    return reg


@pytest.fixture(scope="module")
def rules() -> dict[str, str]:
    assert GRAMMAR.exists(), (
        f"no grammar at {GRAMMAR}. The roadmap row `local-llm-grammar` and "
        "`tools/local-model-bench.py --grammar` both depend on this file."
    )
    return _rules()


def test_every_registry_opcode_is_generatable(registry, rules):
    """The `stage` alternation must name exactly the registry's opcodes."""
    declared = {r[2:] for r in rules if r.startswith("s-")}
    assert declared == set(registry), (
        "grammar stage rules and CORTEX_OPCODES disagree — "
        f"only in grammar: {sorted(declared - set(registry))}; "
        f"only in registry: {sorted(set(registry) - declared)}"
    )

    dispatch = rules.get("stage", "")
    missing = [op for op in registry if f"s-{op}" not in dispatch]
    assert not missing, f"declared but unreachable from `stage`: {missing}"


def test_each_opcode_accepts_exactly_its_registry_namespaces(registry, rules):
    for opcode, (_lo, _hi, namespaces) in registry.items():
        rhs = rules.get(f"e-{opcode}")
        assert rhs is not None, f"no operand rule e-{opcode}"
        assert set(_namespaces_of(rhs)) == set(namespaces), (
            f"{opcode}: grammar admits {sorted(set(_namespaces_of(rhs)))}, "
            f"registry declares {sorted(namespaces)}"
        )


def test_operand_arity_matches_the_registry(registry, rules):
    """min=0 opcodes make the operand optional; min>=1 opcodes require it.

    Expressed structurally rather than by counting tokens: a `min: 0` opcode
    routes through an `optional-e-<op>` rule, a `min: 1` one names `e-<op>`
    directly, and the single `max: 2` opcode (`link`) repeats it.
    """
    for opcode, (lo, hi, _ns) in registry.items():
        rhs = rules[f"s-{opcode}"]
        if lo == 0:
            assert f"optional-e-{opcode}" in rhs, (
                f"{opcode} has min=0 but its stage rule requires an operand"
            )
            assert f"optional-e-{opcode}" in rules, f"no optional-e-{opcode} rule"
        else:
            assert f"e-{opcode}" in rhs and f"optional-e-{opcode}" not in rhs, (
                f"{opcode} has min={lo} but its operand is optional in the grammar"
            )
        occurrences = rhs.count(f"e-{opcode}")
        assert occurrences == hi, (
            f"{opcode}: registry max={hi}, grammar names the operand "
            f"{occurrences}×"
        )


def test_the_stage_bound_is_the_declared_limit(rules):
    """CORTEX_LIMITS.stages is 16, and the grammar encodes it as nested pipes.

    Read from cortex-lang.ts rather than trusted: a bound that drifts silently
    would let a model emit a program the validator always rejects, which is the
    class the grammar exists to remove.
    """
    lang = (REPO / "files/anatomy/cortex/server/cortex-lang.ts").read_text(encoding="utf-8")
    declared = int(re.search(r"stages:\s*(\d+)", lang).group(1))
    pipes = sorted(
        (int(m.group(1)) for r in rules if (m := re.fullmatch(r"pipe(\d+)", r))),
    )
    assert pipes == list(range(1, declared + 1)), (
        f"CORTEX_LIMITS.stages is {declared}; grammar declares pipe rules {pipes}"
    )
    assert rules["pipeline"].count("pipe") >= 2, (
        "pipeline must route both the source and the bare-stage branch through "
        "the bounded chain"
    )


def test_the_bench_reaches_the_grammar_without_going_through_ollama():
    """Ollama drops an unknown `options` key, so a grammar sent that way is a
    knob that constrains nothing (measured 2026-08-22; see the bench header).
    The constrained path must therefore name llama-server."""
    bench = (REPO / "tools/local-model-bench.py").read_text(encoding="utf-8")
    assert "--grammar" in bench, "the bench exposes no grammar mode"
    assert "cortex-lang.gbnf" in bench, "the bench names no grammar file"
    assert "llama-server" in bench, (
        "the bench's grammar mode must go through llama-server; Ollama's API "
        "accepts a grammar and silently ignores it"
    )
    assert "--grammar-file" in bench, (
        "llama-server must be told the grammar at startup, where an unparsable "
        "grammar is a startup failure rather than a silent no-op"
    )
