"""Anatomy CI gate — the `view` block: it must ARRIVE, and it must be NARROWED.

A DataTable's `view` block is the estate's one declarative render contract: the
table says style / titleColumn / facets / highlights / offer, and every renderer
— the Svelte face today, a native one later — inherits that single declaration
from `GET /agent/v1/tables/:slug`. Two failure modes, and this file exists
because BOTH were live on 2026-08-28 rather than hypothetical.

1. IT DID NOT ARRIVE. `view:` had never been forwarded by the nOS seeder, and
   KEAP's create mapping listed `graph: b.graph` and no `view:`. Zod strips what
   it does not know, so a `view:` authored in state/keap-tables/*.table.yml
   validated in git, went green in every offline gate, and reached no converged
   install — as SILENCE, at exit 0. The exact shape CLAUDE.md keeps naming: a
   success marker written by the code that attempted the work. A gate that reads
   the .table.yml and stops there would report the declaration as the fact, so
   this one follows the value along the wire instead.

2. IT ARRIVED UNCHECKED. The block may be filled by a local model, so it is
   untrusted input that happens to be well-formed JSON. `narrowView` is the one
   door; it is one line at the call site, and one line is how a boundary gets
   deleted in a refactor that "simplified an assignment".

Companion runtime gates (the shape is pytest's job, the behaviour is theirs):
  files/anatomy/face/src/lib/tables/lens.test.ts   — vitest, the narrowing rules
  <keap>/server/table-view-meta.test.ts            — vitest, author-time refusal
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
FACE_SRC = REPO / "files" / "anatomy" / "face" / "src"
BFF_TABLES = FACE_SRC / "routes" / "bff" / "tables" / "+server.ts"
VIEW_TS = FACE_SRC / "lib" / "tables" / "view.ts"
CONTRACTS = FACE_SRC / "lib" / "contracts" / "index.ts"
SEEDER = REPO / "roles" / "pazny.keap" / "tasks" / "seed-face-table.yml"
TABLE_DEFS = sorted((REPO / "state" / "keap-tables").glob("*.table.yml"))


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"(?m)//.*$", "", text)


# ── 1. the wire ──────────────────────────────────────────────────────────────


def test_the_seeder_forwards_the_view_block():
    """The playbook half. Without this the definition file is decoration.

    `default(omit)` and not `default({})`: KEAP preserves a card's prior block
    when the key is absent, so a table that declares no style must send NOTHING.
    An empty object is a declaration that the table has no style, and it would
    overwrite one set by any other path.
    """
    src = SEEDER.read_text(encoding="utf-8")
    assert re.search(r"^\s*view:\s*\"\{\{\s*_face_tbl\.def\.view\s*\|\s*default\(omit\)",
                     src, re.MULTILINE), (
        "roles/pazny.keap/tasks/seed-face-table.yml no longer forwards `view:` "
        "with `default(omit)`. A `view:` block in state/keap-tables/*.table.yml "
        "then reaches no converged install, and nothing goes red — this failed "
        "silently for the whole life of the field before 2026-08-28."
    )


# ── 2. the door ──────────────────────────────────────────────────────────────


def test_the_bff_narrows_the_view_block_instead_of_assigning_it():
    """One seam, one check. Retro-red: restoring `table.view = def.view` fails."""
    src = _strip_comments(BFF_TABLES.read_text(encoding="utf-8"))
    assert "narrowView(" in src, (
        "routes/bff/tables/+server.ts does not call narrowView(). The view block "
        "is the only untrusted, model-fillable structure the shell renders from; "
        "assigning it verbatim means a facet or predicate can name any column."
    )
    assert not re.search(r"table\.view\s*=\s*def\.view", src), (
        "routes/bff/tables/+server.ts assigns def.view directly again. That is "
        "the boundary being deleted — narrowView must be the only way in."
    )


def test_narrow_view_reports_what_it_dropped():
    """Absence as absence. A block that quietly lost half of itself renders as
    a working one — the same rule `degradedFrom` already encodes for a style."""
    assert "viewDropped" in CONTRACTS.read_text(encoding="utf-8")
    assert "viewDropped" in _strip_comments(BFF_TABLES.read_text(encoding="utf-8")), (
        "The BFF narrows the block but does not report the casualties. A dropped "
        "facet must reach the header, not just the function's return value."
    )


def test_the_action_catalog_is_code_and_closed():
    """`offer.action` selects from a list the RENDERER owns.

    state/genome/entity.schema.json states the rule for the whole estate — "a
    capability must not be addable by data, so opcodes and handlers stay code,
    per runtime". A `VIEW_ACTIONS` array assembled from the table, or an `action`
    that is a URL or a command string, is that rule inverted.
    """
    src = VIEW_TS.read_text(encoding="utf-8")
    m = re.search(r"export const VIEW_ACTIONS\s*=\s*\[(.*?)\]\s*as const", src, re.DOTALL)
    assert m, "VIEW_ACTIONS is no longer a literal `as const` array in view.ts."
    members = re.findall(r"'([^']+)'", m.group(1))
    assert members, "VIEW_ACTIONS is empty — an offer could never be honoured."
    for a in members:
        assert re.fullmatch(r"[a-z][a-z0-9-]*", a), (
            f"VIEW_ACTIONS member {a!r} is not a plain id. An action is a NAME the "
            f"renderer resolves to a handler, never a command, path or URL."
        )


# ── 3. the declarations ──────────────────────────────────────────────────────


def _defs_with_view():
    out = []
    for p in TABLE_DEFS:
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if isinstance(d.get("view"), dict):
            out.append((p, d))
    return out


@pytest.mark.parametrize("path,defn", _defs_with_view(), ids=lambda x: getattr(x, "name", ""))
def test_every_declared_view_names_only_columns_the_table_has(path, defn):
    """KEAP refuses this at author time; this refuses it before the converge.

    The failure it prevents is not a crash — both runtimes degrade rather than
    throw. It is a facet rendering an empty dropdown, or a highlight selecting
    zero rows and labelling the emptiness with the author's confident words.
    """
    view = defn["view"]
    keys = {c["key"] for c in defn.get("schema", {}).get("columns", [])}
    named: list[tuple[str, str]] = []
    for field in ("titleColumn", "bodyColumn", "dateColumn", "mediaColumn"):
        if view.get(field):
            named.append((field, view[field]))
    for i, c in enumerate(view.get("metaColumns", []) or []):
        named.append((f"metaColumns[{i}]", c))
    for i, c in enumerate(view.get("facets", []) or []):
        named.append((f"facets[{i}]", c))
    for i, h in enumerate(view.get("highlights", []) or []):
        for j, p in enumerate(h.get("when", []) or []):
            named.append((f"highlights[{i}].when[{j}]", p["column"]))
    for j, p in enumerate((view.get("offer") or {}).get("when", []) or []):
        named.append((f"offer.when[{j}]", p["column"]))

    unknown = [f"{where} → {col}" for where, col in named if col not in keys]
    assert not unknown, f"{path.name} declares a view over columns it does not have: {unknown}"


@pytest.mark.parametrize("path,defn", _defs_with_view(), ids=lambda x: getattr(x, "name", ""))
def test_a_declared_view_honours_the_caps_both_runtimes_enforce(path, defn):
    """≤2 facets, ≤4 highlights, ≤4 predicates, ≤1 offer, labels ≤48.

    The caps are duplicated in three places by necessity (a zod schema, a
    TypeScript narrower, this file) because they guard three different moments.
    They are asserted here against the numbers, so a definition cannot be
    authored over a limit and then be silently truncated at render — which reads
    as "the fourth highlight does not match anything".
    """
    view = defn["view"]
    assert len(view.get("facets", []) or []) <= 2, f"{path.name}: >2 facets"
    highlights = view.get("highlights", []) or []
    assert len(highlights) <= 4, f"{path.name}: >4 highlights"
    offer = view.get("offer")
    for h in highlights + ([offer] if offer else []):
        assert 1 <= len(h.get("when", []) or []) <= 4, (
            f"{path.name}: {h.get('label')!r} has {len(h.get('when') or [])} predicates "
            f"(need 1..4 — an empty list matches nothing and is never a shorthand for all)"
        )
    # A highlight label is a chip (48); an offer label is a sentence (120). Both
    # numbers are KEAP's, and the face's narrower matches them — a tighter cap on
    # either side truncates at render something the store accepted, which is the
    # inconsistency this assertion found on its first run.
    for h in highlights:
        assert len(h["label"]) <= 48, f"{path.name}: highlight label over 48 chars"
    if offer:
        assert len(offer["label"]) <= 120, f"{path.name}: offer label over 120 chars"


def test_the_offer_action_is_one_the_face_implements():
    """The cross-repo half of the closed catalog, checked where both are visible.

    KEAP deliberately does NOT validate this — the catalog belongs to whichever
    renderer reads the block, and a store pinning the list would be declaring a
    capability for a runtime it cannot see. So the check lives here, in the repo
    that holds both the declaration and the one renderer that exists.
    """
    src = VIEW_TS.read_text(encoding="utf-8")
    m = re.search(r"export const VIEW_ACTIONS\s*=\s*\[(.*?)\]\s*as const", src, re.DOTALL)
    known = set(re.findall(r"'([^']+)'", m.group(1))) if m else set()
    for path, defn in _defs_with_view():
        offer = defn["view"].get("offer")
        if offer:
            assert offer["action"] in known, (
                f"{path.name} offers action {offer['action']!r}, which the face does not "
                f"implement ({sorted(known)}). The renderer would refuse it and show "
                f"nothing — a declaration that validates and does nothing."
            )
