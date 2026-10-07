"""Every tool listed under `tools/README.md` §Readers only reads.

WHY. §Readers is not just an index: tools/anatomy-graph-gen.py turns each line
into a `reader:` node, and the lexicon files every reader under `sense` — a
part that only reads. On 2026-10-06 a dozen of its lines were writers (a docker
restart, an Object-Lock PUT, a KEAP disposition, file renders), so the body
plan counted limbs as senses. The per-tool gates (test_the_new_readers_only_read
and its siblings) pin one reader each; this one pins the whole section.

HOW. The same method as test_the_new_readers_only_read: the AST, never the
prose. Per listed `.py`: no argv literal with a mutating verb, no file write,
no HTTP verb that changes state, no SQL DML in a string literal, no `--out`
handed to a child. A writer
belongs under §Limbs.

WHAT IT CANNOT SEE. A write hidden in an imported module, a computed argv or
method, or a POST that only reads. Those are judged by reading the tool; the
ones accepted are in EXCEPTIONS with their reason, and that list only shrinks.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from test_the_new_readers_only_read import FORBIDDEN as _BASE_FORBIDDEN
from test_the_new_readers_only_read import WRITE_MODES, _argv_literals

REPO = pathlib.Path(__file__).resolve().parents[2]
README = REPO / "tools/README.md"

FORBIDDEN = {
    **_BASE_FORBIDDEN,
    "docker": {"restart", "stop", "kill", "rm", "rmi", "start", "run", "update",
               "create", "pull", "push", "cp", "up", "down"},
    "launchctl": {"load", "unload", "bootstrap", "bootout", "kickstart", "enable", "disable"},
}
FS_WRITES = {"write_text", "write_bytes", "mkdir", "rmtree", "touch", "unlink",
             "copyfile", "copytree", "copy2", "symlink_to", "makedirs"}
FS_MODULE_WRITES = {"replace", "rename", "remove", "chmod", "move", "copy"}
HTTP_WRITES = {"POST", "PUT", "PATCH", "DELETE"}
DML = re.compile(r"^\s*(insert\s+(or\s+\w+\s+)?into|update\s+\w+\s+set|delete\s+from|"
                 r"replace\s+into|(drop|create|alter)\s+(table|index|view))\b", re.I)

#: Listed tool → why its finding is not a write. Only ever delete lines.
EXCEPTIONS: dict[str, str] = {
    "openhuman-status.py": "the writes are --selftest fixtures inside a TemporaryDirectory",
    "permission-status.py": "`docker run --rm` with a `:ro` mount is how it asks what Docker can see",
    "wing-status.py": "`CREATE TABLE` is a regex over the schema file it reads, not a statement",
}


def _readers() -> list[str]:
    text = README.read_text(encoding="utf-8")
    m = re.search(r"^## Readers[^\n]*\n(.*?)^## ", text, re.S | re.M)
    assert m, "tools/README.md has no `## Readers` section"
    return re.findall(r"^- `([^`]+)`", m.group(1), re.M)


def _docstring_ids(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(node) is not None:
                out.add(id(node.body[0].value))
    return out


def findings(path: pathlib.Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    out = []
    for argv in _argv_literals(path):
        head = argv[0].rsplit("/", 1)[-1]
        bad = sorted(set(argv[1:]) & FORBIDDEN.get(head, set()))
        if bad:
            out.append(f"runs `{head} {' '.join(argv[1:])}`")
        if "--out" in argv:
            out.append(f"hands `--out` to a child: {argv}")
    docs = _docstring_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            if node.value in HTTP_WRITES:
                out.append(f"HTTP {node.value} (line {node.lineno})")
            elif DML.match(node.value):
                out.append(f"SQL `{node.value.strip()[:40]}` (line {node.lineno})")
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "attr", None) or getattr(fn, "id", None)
        recv = getattr(getattr(fn, "value", None), "id", None)
        if name in FS_WRITES or (recv in ("os", "shutil") and name in FS_MODULE_WRITES):
            out.append(f"{name}() (line {node.lineno})")
        if name in ("open", "fdopen"):
            modes = node.args[1:2] + [k.value for k in node.keywords if k.arg == "mode"]
            for m in modes:
                if isinstance(m, ast.Constant) and WRITE_MODES.match(f'"{m.value}"'):
                    out.append(f"open(mode={m.value!r}) (line {node.lineno})")
    return sorted(set(out))


def test_the_section_parses_and_names_real_files():
    names = _readers()
    assert names, "§Readers lists nothing — the section moved"
    for n in names:
        assert (REPO / "tools" / n).is_file(), f"§Readers lists {n}, which is not in tools/"
        assert n.endswith(".py"), f"§Readers lists {n}; this gate reads only Python"


@pytest.mark.parametrize("name", _readers())
def test_every_listed_reader_only_reads(name):
    if name in EXCEPTIONS:
        pytest.skip(EXCEPTIONS[name])
    bad = findings(REPO / "tools" / name)
    assert not bad, (f"tools/{name} is listed under §Readers but acts: {bad}. Move it to "
                     "§Limbs, or split the write into its own tool.")


def test_the_exceptions_only_shrink():
    stale = sorted(n for n in EXCEPTIONS if n not in _readers() or not findings(REPO / "tools" / n))
    assert not stale, f"exceptions no longer needed (delete them): {stale}"


def test_the_detector_sees_a_writer(tmp_path):
    """Positive control: each finding kind fires on a tiny writer."""
    p = tmp_path / "w.py"
    p.write_text('import subprocess, pathlib\nsubprocess.run(["docker", "restart", "x"])\n'
                 'subprocess.run([node, "gen.ts", "--out", "d"])\n'
                 'pathlib.Path("a").write_text("b")\nmethod = "PUT"\n'
                 'q = "INSERT INTO t VALUES (1)"\nopen("f", "w")\n', encoding="utf-8")
    got = " ".join(findings(p))
    for kind in ("docker restart", "--out", "write_text", "PUT", "INSERT", "open(mode='w')"):
        assert kind in got, f"the detector missed {kind}: {got}"
