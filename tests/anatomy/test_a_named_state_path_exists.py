"""Every state/ file a code path names must exist.

WHY (repo-body-plan I-11, 2026-10-07). state/ was re-cut by realm (habitat,
fixtures). A reader that still names the old path does not fail: it finds no
file and reports nothing, which reads as health. This gate reads the string
literals of the code (Python by AST, YAML by parse, the rest with comments
stripped), never prose or docstrings, and refuses a state/ path that is gone.
"""
from __future__ import annotations

import ast
import pathlib
import re
import subprocess

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROOTS = ("tools/", "files/anatomy/bone/", "files/anatomy/wing/", "files/anatomy/pulse/",
         "roles/", "tasks/")
# tools/retro-verify/ holds mutations that name a wrong path on purpose.
SKIP = ("files/anatomy/wing/vendor/", "/node_modules/", "/tests/", "tools/retro-verify/")
# A path a compat read names on purpose, until the converge that retires it.
COMPAT = {
    "state/smoke-catalog.runtime.yml": "nos-smoke fallback until apps_runner writes ~/.nos",
}
PATH = re.compile(
    r"(?:^/?|(?<=[\s'\"`(=:,])|(?<=\}\}/))"
    r"(state/(?:[\w.-]+/)*[\w-][\w.-]*\.(?:ya?ml|json|jsonl|md|gbnf|csv))(?![\w/-])")
# A literal that is a whole path with no extension names a directory.
WHOLE = re.compile(r"/?(state(?:/[\w-][\w.-]*)+?)/?")


def _py(src: str) -> list[str]:
    tree = ast.parse(src)
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)}
    out = [n.value for n in ast.walk(tree)
           if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
    for n in ast.walk(tree):  # REPO / "state" / "x.yml" → "state/x.yml"
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            parts, cur = [], n
            while isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Div):
                parts.append(cur.right)
                cur = cur.left
            parts.append(cur)
            consts: list[str] = []
            for p in reversed(parts):  # one unbroken run of literals only
                if isinstance(p, ast.Constant) and isinstance(p.value, str):
                    consts.append(p.value)
                elif consts:
                    break
            out.append("/".join(consts))
    return out


def _yaml(src: str) -> list[str]:
    out: list[str] = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(k), walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            out.append(x)
    for doc in yaml.safe_load_all(src):
        walk(doc)
    return out


def _code(src: str) -> list[str]:
    """Quoted strings of PHP/shell/JS, with //, # and /* */ comments dropped."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "'\"`":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i + 1:j])
            i = j + 1
        elif src.startswith("/*", i):
            i = src.find("*/", i + 2) % (n + 1) + 2
        elif c == "#" or src.startswith("//", i):
            i = src.find("\n", i) % (n + 1) + 1
        else:
            i += 1
    return out


def _template(src: str) -> list[str]:
    src = re.sub(r"\{#.*?#\}|<!--.*?-->", "", src, flags=re.S)
    return ["\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))]


def _literals(rel: str, src: str) -> list[str]:
    if rel.endswith(".py"):
        return _py(src)
    if rel.endswith((".yml", ".yaml")):
        try:
            return _yaml(src)
        except yaml.YAMLError:
            return _template(src)
    if rel.endswith((".php", ".sh", ".js", ".ts", ".mjs", ".neon", ".latte")):
        return _code(src)
    if rel.endswith(".j2"):
        return _template(src)
    return []


def named_paths(files: list[str]) -> dict[str, set[str]]:
    seen: dict[str, set[str]] = {}
    for rel in files:
        if not rel.startswith(ROOTS) or any(s in "/" + rel for s in SKIP):
            continue
        try:
            src = (REPO / rel).read_text(encoding="utf-8")
            lits = _literals(rel, src)
        except (UnicodeDecodeError, SyntaxError, OSError):
            continue
        for lit in lits:
            for m in PATH.finditer(lit):
                seen.setdefault(m.group(1), set()).add(rel)
            if (m := WHOLE.fullmatch(lit.strip())):
                seen.setdefault(m.group(1), set()).add(rel)
    return seen


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True)
    return out.stdout.split()


def test_the_scan_finds_the_known_readers():
    """Positive control: a scan that finds nothing would pass forever."""
    seen = named_paths(_tracked())
    assert "state/manifest.yml" in seen
    assert "state/habitat/router.yml" in seen, "router-status.py builds it from split parts"
    assert len(seen) >= 20, sorted(seen)


def test_every_named_state_path_exists():
    """A file by its extension anywhere in a literal; a directory only when the
    literal is the whole path (prose inside a string names no directory)."""
    seen = named_paths(_tracked())
    gone = {p: sorted(w)[:3] for p, w in seen.items()
            if p not in COMPAT and not (REPO / p).exists()}
    assert not gone, (
        "code names state/ files that do not exist — a reader of a missing file "
        f"reports nothing, which reads as health: {gone}")
