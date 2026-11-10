"""One journey through the cortex organ: its contract number, its opcode grammar, the
store it holds as debt, its role's env and PATH, and what it vendors or must not copy.

Absorbed (2026-11-10, roadmap gate-diet), one section each:
  test_cortex_contract_number_moves_with_the_bump, test_cortex_grammar_matches_registry,
  test_cortex_store_is_declared_debt, test_cortex_fs_roots_has_default,
  test_cortex_selfmodel_python_has_yaml, test_cortex_lang_vendor_conditions,
  test_cortex_vendored_docs.
Every assert of those files survives here with the same inputs and expectations.
"""
from __future__ import annotations

import pathlib
import re

import pytest
import yaml

from _repo_walk import repo_files

REPO = pathlib.Path(__file__).resolve().parents[2]
CORTEX = REPO / "files" / "anatomy" / "cortex"
SERVER = CORTEX / "server"
OPCODES = SERVER / "cortex-opcodes.ts"


# ── test_cortex_contract_number_moves_with_the_bump ─────────────────────────
# 2026-08-11: CORTEX_CONTRACT_VERSION went to 2, the e2e spec kept asserting 1,
# and Cortex CI stayed red two days over nothing broken. The spec keeps LITERALS
# on purpose (importing the constant is unfalsifiable); this section makes them move.

SPEC = CORTEX / "e2e/validate.spec.ts"


def _declared() -> int:
    m = re.search(
        r"export const CORTEX_CONTRACT_VERSION\s*=\s*(\d+)",
        OPCODES.read_text(encoding="utf-8"),
    )
    assert m, (
        f"CORTEX_CONTRACT_VERSION is no longer declared in "
        f"{OPCODES.relative_to(REPO)}. This gate reads it from there; without it "
        "the gate is blind and the spec is unpinned again."
    )
    return int(m.group(1))


#: EVERY place the spec writes the contract number down, not just the first.
#: The first cut matched only `health.contracts.cortex` and shipped green while
#: `data.contract` — the SAME number on the opcode registry — was still 1.
ASSERTIONS = (
    r"expect\(\s*health\.contracts\.cortex\s*\)\.toBe\(\s*(\d+)\s*\)",
    r"expect\(\s*data\.contract\s*\)\.toBe\(\s*(\d+)\s*\)",
)


def _asserted_all() -> list[int]:
    text = SPEC.read_text(encoding="utf-8")
    found: list[int] = []
    for pattern in ASSERTIONS:
        m = re.search(pattern, text)
        assert m, (
            f"{SPEC.relative_to(REPO)} no longer asserts a literal contract "
            f"number for /{pattern}/. If it now compares against the imported "
            "constant, the assertion cannot fail and the contract version is "
            "pinned by nothing — see this section's comment for why the literal "
            "is deliberate."
        )
        found.append(int(m.group(1)))
    return found


def test_the_spec_asserts_the_version_the_organ_ships() -> None:
    declared, asserted = _declared(), _asserted_all()[0]
    assert asserted == declared, (
        f"the cortex organ ships contract v{declared} and the e2e spec asserts "
        f"v{asserted}. CI fails with 'Expected: {asserted}, Received: {declared}' "
        "and it is not a regression — it is a bump nobody carried into the spec. "
        "Update both copies of validate.spec.ts (the vendored one and KEAP's; "
        "test_vendored_cortex_matches_keap.py compares them byte for byte)."
    )


def test_the_version_is_a_plausible_contract_number() -> None:
    """Guard against a regex that starts matching something else entirely."""
    v = _declared()
    assert 1 <= v <= 99, (
        f"CORTEX_CONTRACT_VERSION read as {v}. That is not a contract version, "
        "so this gate is matching the wrong thing and its verdicts are noise."
    )


@pytest.mark.parametrize("path", ["files/anatomy/cortex/e2e/validate.spec.ts"])
def test_the_spec_the_gate_reads_is_the_spec_ci_runs(path: str) -> None:
    """Cheap guard on the file identity, so the gate cannot drift onto a copy."""
    assert (REPO / path).is_file(), f"{path} is gone; re-point this gate"
    ci = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "cortex" in ci.lower(), (
        "the CI workflow no longer mentions cortex, so the job this gate exists "
        "to keep green may not run at all any more."
    )


def test_every_place_the_spec_writes_the_number_agrees() -> None:
    """Both literals, together — the defect that got past the first version."""
    declared = _declared()
    found = _asserted_all()
    assert all(v == declared for v in found), (
        f"the organ ships contract v{declared} and the spec asserts {found} "
        "across its two surfaces. They are the same number: `contracts.cortex` "
        "on /health and `contract` on the opcode registry. Bump both, in the "
        "vendored copy AND in KEAP's."
    )


# ── test_cortex_grammar_matches_registry ────────────────────────────────────
# state/cortex-lang.gbnf hard-codes what cortex-opcodes.ts declares (names, arity,
# namespaces): a second copy that rots quietly — a new opcode is simply never
# generated and the bench reports a capability gap. Param names/types stay
# POST /agent/v1/validate's job.

GRAMMAR = REPO / "state/cortex-lang.gbnf"

#: `name: 'map', … operands: { min: 1, max: 1, namespaces: ['tax','ent','kg'] }`
_OPCODE_RE = re.compile(
    r"name: '([a-z][a-z0-9-]*)',.*?"
    r"operands: \{ min: (\d+), max: (\d+), namespaces: \[([^\]]*)\] \}",
    re.S,
)


def _registry() -> dict[str, tuple[int, int, list[str]]]:
    src = OPCODES.read_text(encoding="utf-8")
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
    assert OPCODES.exists(), f"no opcode registry at {OPCODES}"
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
    lang = (SERVER / "cortex-lang.ts").read_text(encoding="utf-8")
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


# ── test_cortex_store_is_declared_debt ──────────────────────────────────────
# Ruling 2026-10-07 (cortex-corpus-ruling, option b): Cortex reasons, KEAP is
# memory. The store under server/ is debt named in the `Cortex` lexicon entry and
# may only shrink; store-side files are derived from imports (static ones only).

LEXICON = REPO / "state" / "genome" / "lexicon.yml"
REASONING_ENTRY = ("cortex-validate", "cortex-lang")
STORE_DRIVERS = ("libsql", "./db")
#: The one store file imports cannot tell from shared plumbing: index.ts imports
#: it beside tokens.ts. Its own header calls it "the filesystem seam" fs-sync needed.
SEAMS = ("cortex-fs",)

#: Store-side files under server/, measured 2026-10-07. Only ever lower it.
PINNED = 17

_IMPORT = re.compile(r"""(?:\bfrom\s+|\bimport\s*\(\s*|\bimport\s+|\brequire\(\s*)['"]([.@\w][^'"\s]*)['"]""")


def _imports(server: pathlib.Path) -> dict[str, set[str]]:
    out = {}
    for p in sorted(server.glob("*.ts")):
        src = re.sub(r"/\*.*?\*/", "", p.read_text(encoding="utf-8"), flags=re.S)
        src = re.sub(r"(?m)^\s*//.*$", "", src)
        out[p.name.removesuffix(".ts")] = set(_IMPORT.findall(src))
    return out


def _local(spec: str, mods: dict) -> str | None:
    name = spec.removeprefix("./").removesuffix(".js")
    return name if spec.startswith("./") and name in mods else None


def _closure(start, mods) -> set[str]:
    seen, todo = set(), list(start)
    while todo:
        m = todo.pop()
        if m not in seen:
            seen.add(m)
            todo += [x for s in mods[m] if (x := _local(s, mods))]
    return seen


def store_side(server: pathlib.Path = SERVER) -> set[str]:
    mods = _imports(server)
    deps = {m: {x for s in mods[m] if (x := _local(s, mods))} for m in mods}
    core = _closure(REASONING_ENTRY, mods)
    roots = {m for m in mods if deps[m] & set(REASONING_ENTRY)} - core  # index.ts
    code = {m for m in mods if not m.endswith(".test")} - core - roots
    store = {m for m in code if mods[m] & set(STORE_DRIVERS)} | (set(SEAMS) & code)
    while True:
        up = {m for m in code if deps[m] & store}
        down = {d for d in code if all(m in store for m in mods
                                       if d in deps[m] and not m.endswith(".test"))
                and any(d in deps[m] for m in store)}
        if store | up | down == store:
            break
        store |= up | down
    store |= {m for m in mods if m.endswith(".test") and m.removesuffix(".test") in store}
    return {f"files/anatomy/cortex/server/{m}.ts" for m in store}


def _debt() -> dict:
    words = yaml.safe_load(LEXICON.read_text(encoding="utf-8"))["words"]
    return words["Cortex"].get("debt") or {}


def test_the_store_side_files_only_shrink():
    have = store_side()
    assert len(have) <= PINNED, (
        f"{len(have)} store-side files under {SERVER.relative_to(REPO)} > pinned {PINNED}: "
        f"new store code belongs in KEAP, not Cortex. Files: {sorted(have)}")


def test_every_store_side_file_is_named_in_the_debt_declaration():
    debt = _debt()
    assert debt.get("says") and debt.get("row"), (
        "the Cortex lexicon entry declares no `debt:` (says + row + paths)")
    named = {p for p in debt.get("paths") or [] if p.startswith("files/anatomy/cortex/server/")}
    have = store_side()
    assert named == have, (f"undeclared: {sorted(have - named)}; "
                           f"declared but no longer store-side (delete them): {sorted(named - have)}")


def test_the_debt_declaration_names_real_paths_and_a_real_row():
    debt = _debt()
    assert "files/anatomy/cortex/knowledge/" in (debt.get("paths") or [])
    missing = [p for p in debt.get("paths") or [] if not (REPO / p).exists()]
    assert not missing, f"debt names paths that do not exist: {missing}"
    slugs = {r["slug"] for r in yaml.safe_load((REPO / "state/roadmap/index.yml").read_text())}
    assert debt.get("row") in slugs, f"debt row {debt.get('row')!r} is not a roadmap slug"


def test_the_derivation_sees_a_new_store_file(tmp_path):
    """The derivation itself: a new file importing ./db counts, a core file does not."""
    for p in SERVER.glob("*.ts"):
        (tmp_path / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "new-vectors.ts").write_text("import { getDb } from './db';\n", encoding="utf-8")
    got = store_side(tmp_path)
    assert "files/anatomy/cortex/server/new-vectors.ts" in got
    assert not {f"files/anatomy/cortex/server/{m}.ts" for m in REASONING_ENTRY} & got


# ── test_cortex_fs_roots_has_default ────────────────────────────────────────
# `_cortex_fs_user_roots` is set only `when: cortex_fs_enabled`, but the daemon env
# reads it unconditionally (systemd env, launchd plist): an fs-disabled host (the
# Linux default) died on the undefined var (KEAP×nOS grand review, 2026-09-04).

FS_ROOTS_FILES = [
    REPO / "roles/pazny.cortex/tasks/main.yml",
    REPO / "roles/pazny.cortex/templates/cortex.plist.j2",
]
VAR = "_cortex_fs_user_roots"


def test_every_unguarded_use_has_a_default():
    offenders = []
    for f in FS_ROOTS_FILES:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if VAR not in line:
                continue
            # The set_fact DEFINITION is the assignment, not a `{{ }}` read.
            if re.search(rf"^\s*{VAR}\s*:", line):
                continue
            if "{{" in line and "| default" not in line:
                offenders.append(f"{f.relative_to(REPO)}:{i}")
    assert not offenders, (
        f"{VAR} is read without `| default` at {offenders}; it is set only when "
        "cortex_fs_enabled, so an fs-disabled converge crashes on the undefined var"
    )


# ── test_cortex_selfmodel_python_has_yaml ───────────────────────────────────
# macOS-15 Integration 2026-10-05: no pyenv shim, Homebrew python3 without yaml,
# so `store:materialise` died in keap_selfmodel_gen.py. The `python3` cortex
# spawns must resolve to the nOS tools venv first.

def test_materialise_path_puts_the_tools_venv_before_any_host_python():
    task = next(t for t in yaml.safe_load((REPO / "roles/pazny.cortex/tasks/main.yml").read_text())
                if "Materialise the store" in t.get("name", ""))
    parts = task["environment"]["PATH"].split(":")
    venv = parts.index("{{ nos_tools_venv }}/bin")
    hosts = [i for i, p in enumerate(parts) if "pyenv" in p or "homebrew" in p or p.startswith("/usr")]
    assert all(venv < i for i in hosts), parts


def test_the_tools_venv_carries_pyyaml_and_is_built_before_cortex():
    assert any(ln.lower().startswith("pyyaml") for ln in (REPO / "tools/requirements.txt").read_text().splitlines())
    main = (REPO / "main.yml").read_text()
    assert main.index("tasks/tools-venv.yml") < main.index("name: pazny.cortex")


# ── test_cortex_lang_vendor_conditions ──────────────────────────────────────
# The w-datalog vendor decision oversold termination (no budget: 312,444 facts in
# ~142 s at 790 nodes), hid a fail-open parser and two internal imports. The doc
# must keep declaring the divergence set, and a vendored datalog_reasoner.py must
# honour it (vacuous until one lands; red the day it lands unedited).

DOC = REPO / "docs/archive/idea/02-cortex-lang.md"
LOOP_DOC = REPO / "docs/archive/idea/11-agentic-loop.md"

# The budget parameters the doc commits the vendored copy to. Declared here
# and in the doc; the vendored file must define all three.
BUDGET_TOKENS = ("max_derived_facts", "max_iterations", "max_seconds")


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_the_stdlib_only_claim_is_corrected() -> None:
    text = _doc()
    assert "importing only `re`/`collections`/`dataclasses`/`typing`" not in text, (
        "02-cortex-lang.md is back to claiming the upstream file imports only "
        "four stdlib modules. It imports semantica-internal logging and "
        "progress-tracker modules at seven call sites; a decision that hides "
        "the required edit hides that the vendor is a fork."
    )
    assert "progress_tracker" in text, (
        "the doc no longer names the internal imports the vendored copy must "
        "strip — the divergence set is the vendor contract's comparison "
        "baseline, and an undeclared divergence is what 606046e6 exists to "
        "prevent."
    )


def test_termination_is_not_oversold() -> None:
    text = _doc()
    assert "necessary, not sufficient" in text, (
        "the doc dropped the amendment that termination is necessary, not "
        "sufficient. An unbudgeted fixpoint over model-authored rules is a "
        "resource bomb that happens to halt: 312,444 facts / ~142 s for the "
        "textbook closure at the estate's own 790-node scale."
    )
    for token in BUDGET_TOKENS:
        assert token in text, (
            f"the doc no longer declares the budget cap `{token}`. The vendor "
            "condition is hard caps on derived facts, iterations and wall "
            "time, failing closed — remove one and the vendored-copy half of "
            "this gate loses its baseline."
        )


def test_the_parser_condition_is_declared() -> None:
    text = _doc()
    assert "unconsumed input" in text, (
        "the doc no longer requires the vendored parser to raise on "
        "unconsumed input. Upstream silently strips `not` and comparison "
        "guards — accepting a rule while inverting its semantics is the "
        "opposite of the fail-closed doctrine the same document invokes."
    )


def test_the_loop_doc_credits_the_schema_not_the_implementation() -> None:
    """11-agentic-loop.md §6c: the same upstream, cited for what it measured.

    The section originally credited semantica with 'decisions [as] first-class
    graph nodes with causal ancestry' plus precedent search. Measured: the
    headline `find_similar_decisions()` similarity is bag-of-words Jaccard
    (its `use_semantic_search` parameter is never read), and the headline
    causality is entity co-occurrence plus timestamp order — guessed, not
    recorded. The schema and the PROV-O export are worth taking; the
    implementations are not, and the doc must say which is which.
    """
    text = LOOP_DOC.read_text(encoding="utf-8")
    assert "Jaccard" in text, (
        "§6c no longer says the upstream precedent search is bag-of-words "
        "Jaccard — the citation is back to admiring a docstring."
    )
    assert "co-occurrence" in text, (
        "§6c no longer says the upstream 'causal ancestry' is inferred from "
        "entity co-occurrence — a reader will import guessed lineage as if it "
        "were the recorded actor_action_id kind."
    )
    assert "ships the shape" not in text, (
        "§6c reverted to the unqualified endorsement. Credit the decision "
        "SCHEMA and the PROV-O export; the headline implementations are naive "
        "and this estate's lineage is already recorded, not guessed."
    )


def test_a_vendored_copy_honors_the_declared_conditions() -> None:
    """Vacuous until the file lands; red the day it lands unedited."""
    copies = list(repo_files(REPO, "datalog_reasoner.py"))
    for copy in copies:
        text = copy.read_text(encoding="utf-8")
        for token in BUDGET_TOKENS:
            assert token in text, (
                f"{copy.relative_to(REPO)} was vendored without the declared "
                f"budget cap `{token}` (docs/archive/idea/02-cortex-lang.md). An "
                "unbudgeted derive_all() at 790-node scale is minutes of CPU "
                "from one well-formed rule."
            )
        assert "unconsumed" in text, (
            f"{copy.relative_to(REPO)} was vendored without the strict parser "
            "the decision requires — upstream's regex findall keeps matching "
            "atoms and silently drops `not` and comparison guards."
        )


# ── test_cortex_vendored_docs ───────────────────────────────────────────────
# cortex/docs/specs/ held eight KEAP spec copies nothing could diff (KEAP is not
# checked out here): three different KEAP tags while the pin was v2.0.1
# (hidden_fees/11). ssot/doctrine/cross-repo-contracts.md §1: no local copy.

ORGAN_DOCS = CORTEX / "docs"


def test_no_keap_spec_is_copied_into_the_organ():
    copies = sorted(
        str(p.relative_to(REPO))
        for p in ORGAN_DOCS.rglob("*.md")
        if "Vendored from thisisait/nos-keap" in "\n".join(p.read_text().splitlines()[:6])
    )
    assert not copies, (
        f"KEAP spec copies inside nOS: {copies}. Cite the original as "
        "`KEAP docs/specs/<name>.md` and delete the copy — two copies diverge."
    )


def test_the_specs_dir_is_gone():
    assert not (ORGAN_DOCS / "specs").exists(), (
        "files/anatomy/cortex/docs/specs/ is back; KEAP's specs live in KEAP."
    )
