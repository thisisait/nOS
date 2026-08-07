"""Anatomy gate — `form`, `build` and `layer` are one facet, declared once.

R4 (`docs/idea/13-relations.md`). R1–R3 each added an adjective to the estate's
nodes and each added it in its own place. Measured at 44c90677, before this
file existed:

  * `form` and `build` — TypeScript unions in
    `files/anatomy/face/src/lib/contracts/index.ts:33,49`, plus two `as const`
    arrays whose only reader was the type annotation beside them;
  * `layer` — four string literals inside
    `tools/anatomy-graph-gen.py::derive_layers` and prose in
    `docs/doctrine/layers.md` §3;
  * the anatomy compiler, which harvests the face registry with a regex and
    stamps all three onto nodes, validated **none of them**: `form: 'veiw'`
    compiled into the estate's address space as a fourth form, silently;
  * the genome's own `identity.taxonomy_anchor` — zero producers, zero
    consumers, one grep hit (its own declaration) — while 196 graph nodes
    carried the same fact as `anchor` and its example spelling
    (`tax:02.02.11`) matched none of the 362 live spine ids.

Three adjectives, three registries, no comparison, and one dead fourth
spelling in the file whose whole purpose is to end that. This gate pins the
collapse: ONE declaration (`state/genome/entity.schema.json` `definitions.axes`),
generated into both runtimes by `tools/genome-codegen.py`, consumed by the face
and by the compiler, with a refusal on the way in.

The load-bearing tests here are the two REFUSALS — an axis the genome does not
declare, and a value outside its vocabulary — because those are what make a
fourth adjective a genome edit rather than a fifth file.

CI-safe: pure file + schema work. No Docker, no network, no live host.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
ENTITY = REPO / "state" / "genome" / "entity.schema.json"
CODEGEN = REPO / "tools" / "genome-codegen.py"
GRAPH_GEN = REPO / "tools" / "anatomy-graph-gen.py"
GRAPH = REPO / "state" / "anatomy-graph.json"
PY_GEN = REPO / "files" / "anatomy" / "module_utils" / "nos_entity.py"
TS_GEN = REPO / "files" / "anatomy" / "face" / "src" / "lib" / "contracts" / "entity.gen.ts"
CONTRACTS = REPO / "files" / "anatomy" / "face" / "src" / "lib" / "contracts" / "index.ts"
REGISTRY = REPO / "files" / "anatomy" / "face" / "src" / "lib" / "apps" / "native" / "registry.ts"
GRAPH_TS = REPO / "files" / "anatomy" / "face" / "src" / "lib" / "anatomy" / "graph.ts"
SPINE = REPO / "state" / "fable" / "taxonomy-bundle.json"

jsonschema = pytest.importorskip("jsonschema")


def _entity() -> dict:
    return json.loads(ENTITY.read_text(encoding="utf-8"))


def _axes_facet() -> dict:
    return _entity()["definitions"]["axes"]


def _validator() -> "jsonschema.Draft7Validator":
    return jsonschema.Draft7Validator(_axes_facet())


def _nos_entity():
    """Import the GENERATED module the way the compiler does."""
    spec = importlib.util.spec_from_file_location("nos_entity_axes_gate", PY_GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _graph_gen():
    spec = importlib.util.spec_from_file_location("anatomy_graph_gen_axes_gate", GRAPH_GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def graph() -> dict:
    return json.loads(GRAPH.read_text(encoding="utf-8"))


def _code(path: pathlib.Path) -> str:
    """The file with its PROSE removed. Comments are not code, and this gate's
    own explanations name the vocabularies it forbids restating — R3 learned
    that the expensive way when its `isNativeApp` grep matched the paragraph
    explaining the deletion.

    PER LANGUAGE, and both halves of that cost a false RED on the first draft:

      * stripping `#` lines before Python docstrings removed six triple-quote
        delimiters sitting on commented lines, which re-paired the remaining
        ones and swallowed live code;
      * running the C-style `/* … */` strip over Python ate everything between
        `plugins/*/plugin.yml` and the next `*/` — a glob is not a comment.
    """
    return _code_str(path.read_text(encoding="utf-8"), path.suffix)


def _code_str(text: str, suffix: str = ".py") -> str:
    if suffix == ".py":
        text = re.sub(r'"""(?:.|\n)*?"""', "", text)
        return re.sub(r"^\s*#.*$", "", text, flags=re.M)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


# ── one declaration ───────────────────────────────────────────────────────


def test_the_three_axes_live_in_one_facet():
    """`form`, `build`, `layer` — one `definitions.axes`, composed into the base.

    Not three facets, and not five files. The companion fields belong TO an
    axis (`layer_withheld`, `layer_basis`) and are derived as such by
    `genome-codegen.axis_names`, so promoting one or adding a sixth needs no
    second list."""
    facet = _axes_facet()
    props = set(facet["properties"])
    assert props == {"form", "build", "layer", "layer_withheld", "layer_basis"}, props
    assert _entity()["definitions"]["entity"]["properties"]["axes"] == {
        "$ref": "#/definitions/axes"
    }, "the axes facet is not composed into the base entity"
    assert tuple(_nos_entity().AXES) == ("form", "build", "layer")


def test_a_fourth_adjective_cannot_be_added_by_inventing_a_fifth_file():
    """The declaration-side half of R4's rule, stated as schema.

    `additionalProperties: false` means an entity carrying an undeclared
    adjective fails validation until the axis is added HERE — and adding it
    here is what puts it in every runtime, because one emitter reads this file.
    The artifact-side half is `stamp_axes` (below): the compiled graph is
    stamped before any validator sees it."""
    assert _axes_facet().get("additionalProperties") is False
    errs = [e.message for e in _validator().iter_errors({"form": "view", "mood": "calm"})]
    assert errs, "an undeclared adjective validated — the axes facet is open"
    assert any("mood" in e for e in errs), errs


def test_no_runtime_restates_a_vocabulary_the_genome_owns():
    """The three registries collapse only if the other two stop declaring.

    Keyed on the VALUE LISTS, not on the type names: the face still exports
    `AppForm` from `$lib/contracts` (re-exported from the generated module), and
    the point is that no second file spells out what its members are.

    The rule is WHOLE-vocabulary, which is what separates a restatement from a
    use: `form: 'view'` in the registry is an app declaring itself, and the
    derivation naming L0/L1/L2 is the arithmetic that produces them. Enumerating
    all four is the thing a fifth layer would have to be added to.

    Token-matched, not quote-matched: `n('services_layer_L0')` in graph.ts was a
    fourth copy that a quoted-literal grep read as clean, and it is what this
    check caught on its own first pass."""
    g = _nos_entity()
    offenders = []
    for path in (CONTRACTS, REGISTRY, GRAPH_GEN, GRAPH_TS):
        code = _code(path)
        for axis, vocab in (("form", g.APP_FORMS), ("build", g.APP_BUILDS),
                            ("layer", g.SERVICE_LAYERS)):
            hits = sum(1 for v in vocab
                       if re.search(rf"(?<![A-Za-z0-9]){re.escape(v)}(?![A-Za-z0-9])", code))
            if hits == len(vocab):
                offenders.append(f"{path.relative_to(REPO)} restates the whole `{axis}` "
                                 f"vocabulary {list(vocab)}")
    assert not offenders, (
        "a runtime declares its own copy of a genome vocabulary:\n  " + "\n  ".join(offenders)
    )


def test_the_two_runtimes_carry_the_same_vocabulary():
    """The check that never existed. face ↔ compiler agreement was previously
    a matter of two people typing the same four strings."""
    schema = _axes_facet()["properties"]
    py = _nos_entity()
    ts = TS_GEN.read_text(encoding="utf-8")

    def ts_arr(name: str) -> list[str]:
        m = re.search(rf"export const {name} = \[([^\]]*)\] as const;", ts)
        assert m, f"{name} is not exported from entity.gen.ts"
        return re.findall(r"'([^']*)'", m.group(1))

    assert ts_arr("APP_FORMS") == list(py.APP_FORMS) == schema["form"]["enum"]
    assert ts_arr("APP_BUILDS") == list(py.APP_BUILDS) == schema["build"]["enum"]
    assert ts_arr("SERVICE_LAYERS") == list(py.SERVICE_LAYERS) == [
        v for v in schema["layer"]["enum"] if v is not None
    ]
    assert None in schema["layer"]["enum"], (
        "a withheld layer must be a legal value of the axis, not an absent one"
    )
    assert None not in py.SERVICE_LAYERS and "null" not in py.SERVICE_LAYERS, (
        "the withholding leaked into the vocabulary — it would read as a fifth layer"
    )


# ── the facet describes the estate that exists ────────────────────────────


AXIS_KEYS = ("form", "build", "layer", "layer_withheld", "layer_basis")


def test_the_axes_facet_accepts_every_live_graph_node(graph):
    """The load-bearing test, and the same shape as
    `test_compliance_facet_accepts_every_live_manifest`: a facet that cannot
    validate what already ships is a redesign wearing a schema's clothes."""
    v = _validator()
    carried = 0
    offenders = []
    for nid, n in graph["nodes"].items():
        block = {k: n[k] for k in AXIS_KEYS if k in n}
        if not block:
            continue
        carried += 1
        errs = [e.message for e in v.iter_errors(block)]
        if errs:
            offenders.append(f"{nid}: {errs[0]}")
    assert not offenders, "the axes facet rejects nodes that ship today:\n  " + "\n  ".join(
        offenders[:10]
    )
    assert carried >= 65, (
        f"only {carried} nodes carry an axis — the 2026-08-07 census is 5 face apps "
        f"(form+build) and 63 services (layer). A floor this far below it means a "
        f"harvest broke, not that the estate shrank"
    )


def test_every_axis_value_in_the_artifact_is_from_the_genome(graph):
    g = _nos_entity()
    bad = []
    for nid, n in graph["nodes"].items():
        for axis in g.AXES:
            if axis in n and not g.axis_value_is_declared(axis, n[axis]):
                bad.append(f"{nid}: {axis}={n[axis]!r}")
    assert not bad, "values outside the genome vocabulary reached the address space: " + str(bad)


def test_every_withheld_layer_says_why(graph):
    """38 of 63 services carry no layer. Each is a stated refusal, not a blank."""
    g = _nos_entity()
    silent = [nid for nid, n in graph["nodes"].items()
              if n.get("kind") == "service" and g.withheld_layer_needs_a_reason(n)]
    assert not silent, f"layer withheld with no reason: {silent}"
    withheld = sum(1 for n in graph["nodes"].values()
                   if n.get("kind") == "service" and n.get("layer") is None)
    assert withheld == graph["counts"]["services_layer_withheld"] > 0, (
        "the withheld count and the nodes disagree, or the majority verdict "
        "'we do not know' has quietly vanished from the census"
    )


# ── the refusals ──────────────────────────────────────────────────────────


def test_a_withheld_layer_with_no_reason_is_refused_by_the_schema():
    v = _validator()
    assert [e for e in v.iter_errors({"layer": None})], (
        "a null layer validated with no reason — absence rendered as calm"
    )
    assert [e for e in v.iter_errors({"layer": None, "layer_withheld": "unknown"})], (
        "a 7-character shrug satisfied the withholding reason"
    )
    ok = {"layer": None, "layer_withheld":
          "dependency_survey=not-surveyed — nobody has read this role's upstreams"}
    assert not list(v.iter_errors(ok))


def test_a_placed_layer_with_no_arithmetic_is_refused_by_the_schema():
    v = _validator()
    assert [e for e in v.iter_errors({"layer": "L0"})], (
        "a derived layer validated without the derivation that produced it"
    )
    both = {"layer": "L1",
            "layer_basis": {"height": 1, "dependents": 1, "upstreams": 1},
            "layer_withheld": "x" * 60}
    assert [e for e in v.iter_errors(both)], (
        "a service was placed AND withheld — two answers to one question"
    )
    assert not list(v.iter_errors(
        {"layer": "L1", "layer_basis": {"height": 1, "dependents": 1, "upstreams": 1}}))


def test_the_compiler_refuses_an_axis_the_genome_does_not_declare():
    gen = _graph_gen()
    n: dict = {}
    with pytest.raises(SystemExit):
        gen.stamp_axes("faceapp:x", n, mood="calm")
    assert "mood" not in n


def test_the_compiler_refuses_a_value_outside_the_vocabulary():
    """The defect this closes: nothing ran this check anywhere, for either app
    axis, from the day `form` shipped."""
    gen = _graph_gen()
    for kw in ({"form": "veiw"}, {"form": None}, {"build": "F9"},
               {"build": None}, {"layer": "L4"}):
        with pytest.raises(SystemExit):
            gen.stamp_axes("faceapp:x", {}, **kw)
    ok: dict = {}
    gen.stamp_axes("faceapp:x", ok, form="widget", build="F1")
    assert ok == {"form": "widget", "build": "F1"}


def test_the_compiler_refuses_a_silent_or_unbacked_layer():
    gen = _graph_gen()
    with pytest.raises(SystemExit):
        gen.stamp_axes("service:x", {}, layer=None, layer_withheld="dunno")
    with pytest.raises(SystemExit):
        gen.stamp_axes("service:x", {}, layer="L0")
    with pytest.raises(SystemExit):
        gen.stamp_axes("service:x", {}, layer="L0", layer_basis={"height": 0})


def test_stamp_axes_is_the_only_writer_of_an_adjective():
    """A second writer is a second convention, and the refusals only bind the
    call path they are on.

    CEILING, named rather than discovered: this reads assignments of the three
    axis names. A fourth adjective written as `n["mood"] = ...` is caught by
    nothing here — the schema clause above is what refuses it on a declared
    entity, and neither check sees a brand-new key stamped onto a compiled
    node by hand."""
    src = GRAPH_GEN.read_text(encoding="utf-8")
    start = src.index("def stamp_axes(")
    end = src.index("\ndef ", start + 1)
    body = src[start:end]
    outside = _code_str(src[:start] + src[end:])
    hits = re.findall(r'\w+\[\s*["\'](form|build|layer|layer_basis|layer_withheld)["\']\s*\]\s*=',
                      outside)
    assert not hits, f"an adjective is stamped outside stamp_axes: {hits}"
    for axis in ("form", "build", "layer"):
        assert f'n[axis] = value' in body or f'"{axis}"' in body


def test_the_compiler_consumes_the_generated_genome():
    src = _code(GRAPH_GEN)
    assert "from module_utils import nos_entity" in src, (
        "the compiler does not read the genome — it is back to its own literals"
    )
    for symbol in ("nos_entity.AXES", "nos_entity.axis_value_is_declared",
                   "nos_entity.withheld_layer_needs_a_reason", "nos_entity.ANCHOR_RE"):
        assert symbol in src, f"{symbol} is generated and unread"


# ── anchor: one spelling, and a shape that is checked ─────────────────────


def test_the_anchor_pattern_accepts_the_whole_spine_and_every_node(graph):
    g = _nos_entity()
    spine = [a["id"] for a in json.loads(SPINE.read_text(encoding="utf-8"))["anchor"]]
    assert len(spine) >= 300, "the spine shrank — re-check before trusting it"
    bad = [i for i in spine if not g.ANCHOR_RE.fullmatch(i)]
    assert not bad, f"the genome's anchor pattern rejects live spine ids: {bad[:5]}"
    unshaped = [nid for nid, n in graph["nodes"].items()
                if not g.ANCHOR_RE.fullmatch(str(n.get("anchor")))]
    assert not unshaped, f"nodes carry a malformed anchor: {unshaped[:5]}"
    for wrong in ("tax:02.02.11", "2.2.11", "02.02.11.04", "", "unknown"):
        assert not g.ANCHOR_RE.fullmatch(wrong), f"{wrong!r} passed the anchor shape"


def test_the_dead_taxonomy_anchor_spelling_is_gone():
    """`taxonomy_anchor` had zero producers and zero consumers while 196 nodes
    carried the same fact as `anchor` — the `HubApp.native` shape, inside the
    file that exists to end exactly this. Renamed, not aliased."""
    def keys(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield k
                yield from keys(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from keys(v)

    assert "taxonomy_anchor" not in set(keys(_entity())), (
        "taxonomy_anchor is back as a schema property — one fact, two spellings"
    )
    offenders = []
    for path in [PY_GEN, TS_GEN, CODEGEN, GRAPH_GEN, CONTRACTS]:
        if "taxonomy_anchor" in _code(path):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, f"the dead spelling is referenced in code: {offenders}"


# ── regenerate-and-diff, shown red ────────────────────────────────────────


def test_a_hand_edited_axis_vocabulary_is_caught(tmp_path):
    """The genome's drift gate must cover what R4 added, not merely still pass.

    Proves it on the TypeScript target specifically: the Python one is already
    exercised by test_genome_contract.py, and the face's copy is the one a
    front-end change would be tempted to edit in place."""
    original = TS_GEN.read_text(encoding="utf-8")
    try:
        TS_GEN.write_text(original.replace(
            "export const APP_FORMS = ['view', 'utility', 'widget', 'frame'] as const;",
            "export const APP_FORMS = ['view', 'utility', 'widget', 'frame', 'panel'] as const;",
        ), encoding="utf-8")
        r = subprocess.run([sys.executable, str(CODEGEN), "--check"],
                           capture_output=True, text=True, cwd=REPO)
        assert r.returncode != 0, "a hand-added fifth form passed the drift gate"
        assert "entity.gen.ts" in (r.stdout + r.stderr)
    finally:
        TS_GEN.write_text(original, encoding="utf-8")
