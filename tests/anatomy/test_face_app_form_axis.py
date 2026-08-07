"""Anatomy CI gate — the face's two app axes, and the widget that fills one.

WHAT THIS PINS (docs/idea/13-relations.md §R3, docs/doctrine/face-app-tiers.md):

  1. `form` — what an app IS on screen: view | utility | widget | frame.
     Exactly one per app, always declared.
  2. `build` — what it COSTS to build: F1–F4 / H. Unchanged, keeps its
     prefixes, and stops pretending to be a taxonomy of form.
  3. The two are INDEPENDENT. The gate refuses a population in which one could
     be read off the other, because that is precisely the state the split
     exists to leave: a single field answering two questions.
  4. The binary it replaced (`isNativeApp`, `HubApp.native`) is GONE and may
     not come back. A predicate that can only say "component or iframe" cannot
     express a widget, which is both native and not a window.
  5. `widget` is no longer an empty set — and it is filled by an instance that
     is genuinely there: a component file, a registry entry, a mount point at
     the desktop root, and a node with real edges in the anatomy graph.
  6. The widget's seven nodes are READ FROM the graph artifact, not authored.
     Seven invented nodes would be the padding this repository refuses, so the
     gate reads the component's source and refuses a hard-coded node id.

WHY A PYTHON GATE OVER TYPESCRIPT SOURCE. The same reason
`harvest_weaknesses` reads `weaknesses.py` with a regex: the declaration lives
in the face's own module, the CI that must not go green without it is pytest,
and importing a Svelte-flavoured toolchain to read five literals buys nothing.
The vitest suite (`registry.test.ts`, `graph.test.ts`) checks the RUNTIME
behaviour; this checks that the declarations exist at all.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FACE = REPO / "files" / "anatomy" / "face" / "src"
REGISTRY = FACE / "lib" / "apps" / "native" / "registry.ts"
CONTRACTS = FACE / "lib" / "contracts" / "index.ts"
PAGE = FACE / "routes" / "+page.svelte"
WIDGET = FACE / "lib" / "apps" / "widgets" / "AnatomyWidget.svelte"
WIDGET_LAYER = FACE / "lib" / "apps" / "widgets" / "WidgetLayer.svelte"
GRAPH_ARTIFACT = REPO / "state" / "anatomy-graph.json"

FORMS = {"view", "utility", "widget", "frame"}
BUILDS = {"F1", "F2", "F3", "F4", "H"}

_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*|<!--.*?-->", re.S)


def _code(text: str) -> str:
    """Source with comments removed. A gate that greps raw text cannot tell a
    call site from a paragraph EXPLAINING why the call site is gone — and this
    file's whole subject is a symbol whose removal has to be documented
    somewhere. Same reason `tools/face-wiring-report.py` strips first."""
    return _COMMENT.sub("", text)


def _registry_blocks() -> list[dict[str, str]]:
    """Every `registerNativeApp({…})` literal in the registry, as flat dicts.

    Same parse the graph generator runs (tools/anatomy-graph-gen.py
    harvest_faceapps) — deliberately, so the two can never disagree about what
    the registry says.
    """
    text = REGISTRY.read_text(encoding="utf-8")
    out = []
    for body in re.findall(r"registerNativeApp\(\{(.*?)\n\t\}\);", text, re.S):
        fields = dict(re.findall(r"\b(\w+):\s*'([^']*)'", body))
        if fields.get("slug"):
            out.append(fields)
    return out


@pytest.fixture(scope="module")
def apps() -> list[dict[str, str]]:
    got = _registry_blocks()
    assert got, "no registerNativeApp({…}) blocks parsed — the registry moved"
    return got


@pytest.fixture(scope="module")
def graph() -> dict:
    return json.loads(GRAPH_ARTIFACT.read_text(encoding="utf-8"))


# ── 1+2: both axes declared, per app ──────────────────────────────────────


def test_every_registered_app_declares_exactly_one_form(apps):
    for a in apps:
        assert a.get("form") in FORMS, f"{a['slug']}: form={a.get('form')!r} not in {FORMS}"


def test_every_registered_app_declares_a_build_tier(apps):
    """Every app in THIS registry is component-backed, so every one of them was
    built by someone and has a build cost. (A `frame` legitimately has none —
    it is a service, not an agent-built face app — but frames are registered
    from the hub catalog at runtime, never here.)"""
    for a in apps:
        assert a.get("build") in BUILDS, f"{a['slug']}: build={a.get('build')!r} not in {BUILDS}"
        assert a["form"] != "frame", (
            f"{a['slug']}: a frame is registered from the hub catalog "
            f"(registerHubFrames), never as a built-in with a component"
        )


# ── 3: independence, measured rather than asserted ────────────────────────


def test_the_two_axes_are_not_a_relabelling_of_each_other(apps):
    """If `build` were a function of `form`, every app sharing a form would
    share a build, and the split would be cosmetic. Measured 2026-08-07: the
    four views span F1/F2/F3, and F1 is worn by both a view and a widget."""
    by_form: dict[str, set[str]] = {}
    by_build: dict[str, set[str]] = {}
    for a in apps:
        by_form.setdefault(a["form"], set()).add(a["build"])
        by_build.setdefault(a["build"], set()).add(a["form"])
    assert any(len(v) > 1 for v in by_form.values()), (
        "every form maps to exactly one build — the two fields are one field "
        "with two names; either the population is wrong or the split is"
    )
    assert any(len(v) > 1 for v in by_build.values()), (
        "every build maps to exactly one form — same collapse, other direction"
    )


def test_no_code_derives_one_axis_from_the_other():
    """A lookup table from one axis to the other is the derivation the doctrine
    forbids: it would make a declared field a computed one, silently."""
    for path in sorted(FACE.rglob("*.ts")) + sorted(FACE.rglob("*.svelte")):
        text = path.read_text(encoding="utf-8")
        for pat in (r"form\s*===?\s*'(?:view|utility|widget|frame)'\s*\?\s*'F[1-4H]'",
                    r"BUILD_(?:BY|FOR)_FORM", r"FORM_(?:BY|FOR)_BUILD",
                    r"build\s*===?\s*'F[1-4H]'\s*\?\s*'(?:view|utility|widget|frame)'"):
            assert not re.search(pat, text), f"{path.relative_to(REPO)}: derives one axis from the other"


# ── 4: the binary is gone and stays gone ──────────────────────────────────


def test_the_isnative_binary_is_deleted(apps):
    """`isNativeApp` answered one question — component or iframe — and could
    not express a widget at all. `appForm()` replaced it. The whole face is
    swept, not just the registry: a re-introduction anywhere is the field
    coming back."""
    offenders = []
    for path in sorted(FACE.rglob("*.ts")) + sorted(FACE.rglob("*.svelte")):
        text = _code(path.read_text(encoding="utf-8"))
        for m in re.finditer(r"\bisNativeApp\b", text):
            line = text.count("\n", 0, m.start()) + 1
            offenders.append(f"{path.relative_to(REPO)}:~{line}")
    assert not offenders, "isNativeApp is back: " + ", ".join(offenders)


def test_the_dead_hubapp_native_flag_is_gone():
    """`HubApp.native?: boolean` had zero producers and zero consumers for its
    whole life (measured 2026-08-07). It was not replaced by `form` on the same
    interface — a hub entry's form is a property of the render path, so putting
    it back on the catalog type would recreate the same unset field."""
    text = CONTRACTS.read_text(encoding="utf-8")
    assert not re.search(r"^\s*native\??:\s*boolean", text, re.M), (
        "HubApp.native is back — an interface field nothing sets is not a fact"
    )
    # Both axes must still be reachable from `$lib/contracts` — the shell's one
    # import surface. Since R4 (2026-08-07) they are RE-EXPORTED rather than
    # declared here: the vocabulary lives in state/genome/entity.schema.json and
    # is generated into ./entity.gen.ts, so this file must name them without
    # spelling their members. `tests/anatomy/test_genome_axes_facet.py` is what
    # refuses a second copy of the values.
    for axis in ("AppForm", "AppBuild"):
        assert re.search(rf"export type[^;]*\b{axis}\b", text, re.S), (
            f"the {axis} axis is not exported from the contracts"
        )
    assert "./entity.gen" in text, (
        "the app axes are no longer sourced from the generated genome contract"
    )


def test_the_form_axis_is_the_shells_render_switch():
    """The desktop root must branch on `form`, not on a resurrected binary."""
    page = PAGE.read_text(encoding="utf-8")
    assert "appForm(win.app)" in page, "+page.svelte does not decide the window body from `form`"


# ── 5: `widget` is non-empty, by something that is really there ───────────


def test_widget_is_no_longer_an_empty_set(apps):
    widgets = [a for a in apps if a["form"] == "widget"]
    assert widgets, "form=widget has no instances — R3 shipped the name without the thing"
    for w in widgets:
        assert w["build"] in BUILDS


def test_the_widget_has_a_component_and_a_mount_point():
    assert WIDGET.exists(), f"{WIDGET.relative_to(REPO)} missing"
    assert WIDGET_LAYER.exists(), f"{WIDGET_LAYER.relative_to(REPO)} missing"
    page = PAGE.read_text(encoding="utf-8")
    assert "<WidgetLayer" in page, (
        "the widget layer is not mounted at the desktop root — a widget nothing "
        "renders is a registry row, not a surface"
    )


def test_a_widget_is_not_a_window():
    """The distinction `form=widget` records. `launchNative` must refuse it, or
    a widget is just a window with a different label."""
    text = REGISTRY.read_text(encoding="utf-8")
    m = re.search(r"export function launchNative\(.*?\n\}", text, re.S)
    assert m, "launchNative not found"
    assert "'widget'" in m.group(0), (
        "launchNative does not refuse form=widget — opening a window around a "
        "surface already on screen"
    )


# ── 6: the seven nodes are real, and the rule is on screen ────────────────


def test_the_widget_reads_the_graph_artifact_rather_than_literals():
    """Seven invented nodes would be exactly the padding this repo refuses.
    The component must import the artifact and must not carry a node id."""
    text = WIDGET.read_text(encoding="utf-8")
    assert "anatomy-graph.json" in text, "the widget does not read the graph artifact"
    assert "spotlight(" in text, "the widget does not use the stated selection rule"
    body = text.split("<script")[1] if "<script" in text else text
    hard_coded = re.findall(
        r"'(?:pulse|judge|gateset|weakness|daemon|service|resource|repo|tofu|"
        r"authentik|table|doctrine):[^']+'", body)
    # The widget's OWN node id is allowed: it is the recursion, and the code
    # states it as a claim that the gate below checks against the artifact.
    hard_coded = [h for h in hard_coded if h.strip("'") != "faceapp:anatomy-widget"]
    assert not hard_coded, f"hard-coded graph node ids in the widget: {hard_coded}"


def test_the_selection_rule_is_rendered_not_just_commented():
    """A rule the operator cannot read is a rule they cannot check. `spot.rule`
    must reach the markup."""
    text = WIDGET.read_text(encoding="utf-8")
    markup = text.split("</script>")[-1]
    assert "spot.rule" in markup, "the selection rule is not printed on the widget"
    assert "spot.components" in markup, (
        "the widget does not say how many components its sample has — a sample "
        "drawn as one connected whole when it is two fragments is the lie"
    )


def test_the_widget_never_claims_live_and_never_rests_on_green():
    text = WIDGET.read_text(encoding="utf-8")
    markup = text.split("</script>")[-1]
    assert not re.search(r"\[\s*live\s*\]", markup, re.I), (
        "a `[live]` badge over a 60 s poll of a build-time artifact"
    )
    assert 'tone="ok"' not in markup, (
        "the widget rests on --ok green; a surface with nothing to say uses neutral"
    )
    # The four distinct states, none of them collapsed into another.
    for kind in ('kind="loading"', 'kind="unwired"', 'kind="error"', 'kind="empty"'):
        assert kind in markup, f"the widget cannot render {kind} — absence would read as calm"


# ── the recursion: the widget is in the graph it draws ────────────────────


def test_the_widget_is_a_node_with_real_edges(graph):
    """PART C. `widget` stops being an empty set by an instance that is
    genuinely there — including in the address space."""
    nodes, edges = graph["nodes"], graph["edges"]
    wid = "faceapp:anatomy-widget"
    assert wid in nodes, "the widget is not in the graph it renders"
    n = nodes[wid]
    assert n["form"] == "widget" and n["build"] == "F1"
    assert n["hosted_by"] == "service:face"
    assert "anatomy-graph.json" in n["reads_artifact"]

    touching = {(e["from"], e["to"], e["kind"]) for e in edges if wid in (e["from"], e["to"])}
    for want in (
        ("service:face", wid, "data"),                          # mounted at the root
        (wid, "faceapp:anatomy", "trigger"),                    # click-through
        ("daemon:eu.thisisait.nos.wing", wid, "data"),          # what it reads
    ):
        assert want in touching, f"missing declared edge {want}; have {sorted(touching)}"


def test_no_face_app_node_is_a_duplicate_of_a_service(graph):
    """The ~37 frames are NOT emitted as face-app nodes: each already has a
    `service:` address, and a second one for the same thing is padding."""
    nodes = graph["nodes"]
    faceapps = {k for k, v in nodes.items() if v["kind"] == "faceapp"}
    assert faceapps, "no faceapp nodes — the harvest broke"
    for nid in faceapps:
        assert nodes[nid]["form"] != "frame", f"{nid}: a frame was minted a second address"
        slug = nid.split(":", 1)[1]
        assert f"service:{slug}" not in nodes, f"{nid} duplicates service:{slug}"


def test_the_widget_does_not_promote_itself_into_its_own_sample(graph):
    """The rule picks the seven, not the author. The widget's degree is 3 and
    it is nowhere near the top — if it ever were, that would be because the
    estate wired it, not because it drew itself in."""
    deg: dict[str, int] = {}
    for e in graph["edges"]:
        if e["kind"] == "mutex":
            continue
        for end in (e["from"], e["to"]):
            deg[end] = deg.get(end, 0) + 1
    top = sorted(graph["nodes"], key=lambda k: (-deg.get(k, 0), k))[:7]
    assert len(top) == 7
    # Not an assertion that the widget is absent — that would break the day the
    # estate genuinely wires it. An assertion that nothing SHORTCUTS the rule.
    text = WIDGET.read_text(encoding="utf-8")
    assert "spotlight(graph, 7)" in text, "the widget does not take its seven from the rule"
