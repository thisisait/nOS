"""Anatomy gate — the controller's Python is declared once, and covers what nOS imports.

THE SYMPTOM (2026-11-01, a fresh Ubuntu host). The first converge died 114 tasks in:
``password_hash`` needs passlib, which nothing declared; the Mac had it by accident of
pyenv, CI never hashes a login. bootstrap/05-config.sh copied two templates that no
longer existed, and bootstrap.sh was macOS-only.

THE CHECK. Every third-party module imported unguarded by controller-side code
(callback/filter plugins, the custom modules, which run under ansible_playbook_python)
and every package a used filter needs is in bootstrap/requirements-controller.txt;
the bootstrap installs from that file; every file a bootstrap step copies exists.

CEILING. Parses imports and filter names, not what runs; a guarded optional import
is not required. The effect is a fresh host's converge.
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQ = ROOT / "bootstrap" / "requirements-controller.txt"
CODE = ["callback_plugins", "filter_plugins", "files/anatomy/library", "files/anatomy/module_utils"]
DIST = {"yaml": "pyyaml", "jinja2": "jinja2", "requests": "requests"}  # import name -> distribution
FILTERS = {"password_hash": "passlib", "json_query": "jmespath"}


def _declared() -> set[str]:
    names = set()
    for line in REQ.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Za-z0-9_.-]+)", line.split("#")[0])
        if m:
            names.add(m.group(1).lower())
    return names


def _local() -> set[str]:
    return {p.stem for d in CODE + ["tools"] for p in (ROOT / d).rglob("*.py")} | {
        p.name for d in CODE for p in (ROOT / d).rglob("*") if p.is_dir()}


def _unguarded_imports() -> dict[str, str]:
    skip = set(sys.stdlib_module_names) | {"ansible", "ansible_collections", "__future__"} | _local()
    out = {}
    for d in CODE:
        for f in (ROOT / d).rglob("*.py"):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            guarded = {id(m) for t in ast.walk(tree) if isinstance(t, ast.Try)
                       and any(h.type is not None for h in t.handlers) for m in ast.walk(t)}
            for n in ast.walk(tree):
                if id(n) in guarded:
                    continue
                if isinstance(n, ast.Import):
                    tops = [a.name.split(".")[0] for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                    tops = [n.module.split(".")[0]]
                else:
                    continue
                for t in tops:
                    if t not in skip:
                        out.setdefault(t, str(f.relative_to(ROOT)))
    return out


def test_every_unguarded_import_is_declared():
    declared = _declared()
    missing = {imp: where for imp, where in _unguarded_imports().items() if DIST.get(imp, imp).lower() not in declared}
    assert not missing, f"controller code imports what requirements-controller.txt does not declare: {missing}"


def test_every_used_filter_package_is_declared():
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for g in ("main.yml", "tasks/**/*.yml", "roles/**/*.yml", "roles/**/*.j2") for p in ROOT.glob(g))
    need = {pkg for flt, pkg in FILTERS.items() if re.search(rf"\|\s*{flt}\b", text)}
    assert need <= _declared(), f"filters in use need {sorted(need - _declared())}, not in requirements-controller.txt"


def test_the_bootstrap_installs_from_the_list():
    assert "requirements-controller.txt" in (ROOT / "bootstrap" / "03-ansible.sh").read_text(encoding="utf-8")


def test_a_bootstrap_step_copies_only_files_that_exist():
    for step in sorted((ROOT / "bootstrap").glob("0*.sh")):
        for src in re.findall(r'cp\s+"\$PLAYBOOK_DIR/([^"]+)"', step.read_text(encoding="utf-8")):
            assert (ROOT / src).is_file(), f"{step.name} copies {src}, which the repo does not have"
