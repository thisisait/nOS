"""One journey through the face shell's own artifacts: its wiring report, its config
DataTables, its design tokens, its body cap and the layout pin its lane checks.

Absorbed (2026-11-10, roadmap gate-diet), one section each:
  test_face_wiring_contract, test_face_datatable_defs, test_face_tokens_are_design_tokens,
  test_face_upload_cap, test_face_layout_pin_binds_the_graph.
Every assert of those files survives here with the same inputs and expectations.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
FACE_ROOT = REPO / "files" / "anatomy" / "face"
FACE = FACE_ROOT / "src"


# ── test_face_wiring_contract ───────────────────────────────────────────────
# The face is wired by a few load-bearing contracts (ssot/doctrine/face.md):
# forward_auth + edge token, Wing catalog, Bone VFS, KEAP DataTables. The gate
# runs the SAME checks as tools/face-wiring-report.py, so the two cannot drift.

_REPORT = REPO / "tools" / "face-wiring-report.py"


def _load_report():
    spec = importlib.util.spec_from_file_location("face_wiring_report", _REPORT)
    assert spec and spec.loader, "cannot load tools/face-wiring-report.py"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


REPORT = _load_report()


@pytest.mark.parametrize("label,fn", REPORT.CHECKS, ids=[c[0] for c in REPORT.CHECKS])
def test_face_wiring_check_passes(label, fn):
    fails = fn()
    assert fails == [], f"{label}: " + "; ".join(fails)


# ── test_face_datatable_defs ────────────────────────────────────────────────
# The shell's chrome (layouts, wallpapers, controls) is DataTable-driven. Each
# config def in state/keap-tables/ mirrors the apps/systems shape and is paired
# with a seeder, so a def cannot ship without landing in KEAP.

TABLES = REPO / "state" / "keap-tables"
# Read from the BFF, not listed: a hand list missed face-dock (loaded, no def).
_BFF = FACE / "routes" / "bff" / "tables" / "+server.ts"
CONFIG_TABLES = re.findall(
    r"'face-([a-z0-9-]+)'",
    re.search(r"KNOWN_CONFIG_TABLES = \[([^\]]*)\]", _BFF.read_text(encoding="utf-8")).group(1),
)


def _load(name: str) -> dict:
    raw = (TABLES / f"{name}.table.yml").read_text(encoding="utf-8")
    return yaml.safe_load(re.sub(r"\{\{[^}]+\}\}", "TEMPLATE", raw)) or {}


@pytest.mark.parametrize("name", CONFIG_TABLES)
def test_config_table_def_exists_and_parses(name):
    f = TABLES / f"{name}.table.yml"
    assert f.is_file(), f"missing config DataTable def {f.relative_to(REPO)}"
    d = _load(name)
    assert isinstance(d, dict) and d, f"{name}.table.yml did not parse to a mapping"


@pytest.mark.parametrize("name", CONFIG_TABLES)
def test_config_table_mirrors_catalog_shape(name):
    """Same spine as apps.table.yml / systems.table.yml."""
    d = _load(name)
    for key in ("title", "description", "driver", "visibility", "schema"):
        assert key in d, f"{name}.table.yml missing top-level '{key}'"
    assert d["driver"] == "libsql", f"{name}.table.yml driver must be libsql"
    cols = (d.get("schema") or {}).get("columns")
    assert cols, f"{name}.table.yml has no schema.columns"
    for col in cols:
        assert "key" in col and "kind" in col, f"{name} column missing key/kind: {col}"
    keys = {c["key"] for c in cols}
    assert "slug" in keys, f"{name}.table.yml must have a 'slug' column (row identity)"


def test_config_tables_are_read_from_the_bff():
    assert {"layouts", "wallpapers", "controls"} <= set(CONFIG_TABLES), CONFIG_TABLES


def test_config_tables_have_a_seeder():
    seeders = list((REPO / "roles" / "pazny.keap" / "tasks").glob("seed-face-table*.yml"))
    assert seeders, "no KEAP seeder for the face config DataTables"
    blob = "".join(p.read_text(encoding="utf-8") for p in seeders)
    for name in CONFIG_TABLES:
        assert f"{name}.table.yml" in blob, f"seeder does not reference the {name} table"


def test_seeder_create_body_forwards_the_share_model():
    """The ONE create body (seed-face-table.yml) must forward every field the
    create contract accepts — a dropped field validates in git and reaches no
    converged install, silently (the `view:` incident, then `sharedWith`).
    §dtt-share-model: visibility AND the explicit ACL both reach the door.
    """
    body = (REPO / "roles" / "pazny.keap" / "tasks" / "seed-face-table.yml").read_text(encoding="utf-8")
    for field in ("visibility:", "sharedWith:", "view:", "anchors:", "columns:"):
        assert field in body, f"seed-face-table.yml create body drops {field!r}"
    # sharedWith must ride `omit`, never `[]` — an empty list would clear an
    # ACL the definition file simply does not carry (settlement in the seeder).
    assert re.search(r"sharedWith:.*def\.sharedWith \| default\(omit\)", body), \
        "sharedWith must forward `def.sharedWith | default(omit)`, not a literal"


# ── test_face_tokens_are_design_tokens ──────────────────────────────────────
# Ruling 2026-10-16: the vendored design system wins over app.css. The face keeps
# its variable names as aliases rendered by tools/design-sync.py into tokens.css;
# two copies of one colour drift the day app.css sets it by hand.

DESIGN = REPO / "files/anatomy/design"
TOKENS_CSS = FACE / "lib/design/tokens.css"
APP_CSS = FACE / "app.css"
THEME = "glass-face"
# `--name: value; /* token */` — every generated property names its design source.
DECL = re.compile(r"^\s*(--[\w-]+):\s*([^;]+);\s*/\*\s*([\w-]+)\s*\*/", re.M)
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")


def _generated() -> dict[str, tuple[str, str]]:
    return {n: (v.strip(), t) for n, v, t in DECL.findall(TOKENS_CSS.read_text())}


def _root(css: str) -> str:
    m = re.search(r":root\s*\{(.*?)\}", css, re.S)
    return m[1] if m else ""


def test_every_face_colour_equals_its_glass_face_token():
    colours = {c["name"]: c["value"][THEME] for c in json.loads((DESIGN / "tokens.json").read_text())["color"]["tokens"]}
    gen = _generated()
    assert {"--bg", "--fg", "--glass", "--accent", "--ok", "--warn", "--bad"} <= set(gen), sorted(gen)
    wrong = {n: (v, t, colours.get(t)) for n, (v, t) in gen.items()
             if n != "--glass-filter" and colours.get(t) != v}
    assert not wrong, f"face value != design {THEME} token: {wrong}"


def test_the_glass_effect_is_the_design_css_value():
    """tokens.json has no effect group; the value is the vendored design CSS's glass rule."""
    src = re.search(r"\bbackdrop-filter:\s*([^;]+);", (DESIGN / "components.css").read_text())
    assert src, "vendored components.css carries no backdrop-filter"
    assert _generated().get("--glass-filter", ("",))[0] == src[1].strip()


def test_app_css_imports_the_tokens_and_types_no_colour_they_own():
    app = APP_CSS.read_text()
    assert re.match(r"\s*@import\s+['\"]\./lib/design/tokens\.css['\"];", app), "app.css must import tokens.css first"
    owned = sorted(n for n in _generated() if re.search(rf"^\s*{re.escape(n)}\s*:", app, re.M))
    assert not owned, f"app.css re-sets generated variables: {owned}"
    typed = COLOUR.findall(_root(app))
    assert not typed, f"app.css :root hand-types colours {typed}: map them to a design token or derive them"
    assert not re.search(r"backdrop-filter:\s*blur\(", app), "the glass effect is var(--glass-filter), not typed"


# ── test_face_upload_cap ────────────────────────────────────────────────────
# 2026-09-23: a 2 MB upload through /bff/vfs answered 500 — adapter-node's 512 KB
# default errors the stream mid-pipe to Bone. The shell's BODY_SIZE_LIMIT must
# admit what Bone's _MAX_UPLOAD_BYTES stores; both read from their real artifacts.

COMPOSE = REPO / "roles/pazny.face/templates/compose.yml.j2"
DEFAULTS = REPO / "roles/pazny.face/defaults/main.yml"
BONE_VFS = REPO / "files/anatomy/bone/vfs.py"


def _bone_cap() -> int:
    m = re.search(r"^_MAX_UPLOAD_BYTES\s*=\s*([0-9 *]+)", BONE_VFS.read_text(), re.M)
    assert m, "bone/vfs.py no longer declares _MAX_UPLOAD_BYTES"
    return eval(m.group(1).strip(), {"__builtins__": {}})  # noqa: S307 — digits and * only


def _face_cap() -> int:
    """The number the container actually gets: the template's default filter."""
    env = COMPOSE.read_text()
    m = re.search(r'BODY_SIZE_LIMIT:\s*"\{\{\s*(\w+)\s*\|\s*default\((\d+)\)\s*\}\}"', env)
    assert m, "the face compose template does not set BODY_SIZE_LIMIT from a defaulted var"
    var, inline_default = m.group(1), int(m.group(2))
    d = re.search(rf"^{var}:\s*(\d+)", DEFAULTS.read_text(), re.M)
    assert d, f"{var} is used in the template but not declared in defaults/main.yml"
    declared = int(d.group(1))
    assert declared == inline_default, (
        f"{var} is {declared} in defaults but the template falls back to {inline_default} — "
        "two spellings of one ceiling drift apart silently"
    )
    return declared


def test_the_shell_admits_what_bone_will_store():
    bone, face = _bone_cap(), _face_cap()
    assert face >= bone, (
        f"the shell caps an incoming body at {face} B but Bone stores up to {bone} B — "
        "adapter-node kills the stream mid-pipe and the browser gets a bare 500"
    )


def test_the_cap_is_large_enough_for_a_photograph():
    """The concrete failure this was found by: a camera shot is megabytes."""
    assert _face_cap() >= 8 * 1024 * 1024, (
        "a phone photograph is 2-5 MB; a cap under that makes the camera button "
        "in the Files app decorative"
    )


# ── test_face_layout_pin_binds_the_graph ────────────────────────────────────
# The forceLayout pin hashes positions computed from anatomy-graph.json; since
# 2026-11-08 the binding is `anatomy-graph-gen.py --check`. What stays: both
# files exist, and the pin is tab-indented the way the face lane's prettier checks
# (2026-08-29: a json.dumps(indent=2) re-freeze went green here, red in face CI).

ANATOMY_LIB = FACE / "lib" / "anatomy"
PIN = ANATOMY_LIB / "graphLayout.force.pin.json"
GRAPH = ANATOMY_LIB / "anatomy-graph.json"


def test_the_pin_and_the_graph_exist():
    """Positive control — a moved file must not read as a passing bind."""
    assert PIN.is_file(), f"pin missing at {PIN}"
    assert GRAPH.is_file(), f"graph missing at {GRAPH}"


def test_the_pin_is_written_the_way_the_face_lane_will_check_it() -> None:
    prettierrc = json.loads((FACE_ROOT / ".prettierrc").read_text(encoding="utf-8"))
    if not prettierrc.get("useTabs"):
        return  # the shell changed its mind; prettier --check is then the only judge
    body = PIN.read_text(encoding="utf-8")
    offenders = [i + 1 for i, line in enumerate(body.splitlines())
                 if line.startswith(" ")]
    assert not offenders, (
        f"{PIN.name} is space-indented at line(s) {offenders}; the face lane runs "
        "`prettier --check` with useTabs:true and will fail. Re-freeze with "
        "`npx prettier --write` after writing it, or edit it by hand — a "
        "`json.dumps(indent=2)` re-freeze passes every gate in THIS lane and "
        "reddens the other one."
    )
    assert body.endswith("\n"), f"{PIN.name} has no trailing newline; prettier requires one"
