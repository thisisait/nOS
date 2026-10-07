"""Anatomy gate — the store inside Cortex is declared debt, and it may only shrink.

WHY (operator ruling 2026-10-07, roadmap row `cortex-corpus-ruling`, option b:
the lexicon wins). Cortex reasons; KEAP is memory. The libsql store, fs-sync,
embeddings and ANN index under files/anatomy/cortex/ are a replica of memory
held for the onto1 digest. They stay until after v0.17, so they are named as
transitional debt in the `Cortex` lexicon entry (rendered to docs/glossary.md).

The store-side files are derived from the files' own imports: the reasoning
core is the import closure of cortex-validate.ts and cortex-lang.ts; a file
outside it that imports libsql or ./db is store-side, and so is a file that
imports one, a file only store files import, and their tests. index.ts imports
cortex-validate too, so it wires both halves and is neither. SEAMS is the one name
imports cannot place.

CEILING. Only static `import`/`from`/`require` specifiers are read; a store
reached through a dynamic path string is not seen.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SERVER = REPO / "files" / "anatomy" / "cortex" / "server"
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
