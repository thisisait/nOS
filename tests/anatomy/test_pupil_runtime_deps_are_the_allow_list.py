"""The pupil ships no third-party runtime code, installs nothing that runs, and stays small.

WHY. Everything the pupil draws came from a model, and it runs in a window on the
operator's Mac. A runtime npm package is code nobody here wrote inside that window, and
an install script runs on the build host before any gate looks (operator ruling
2026-10-13: no libraries; scales and shapes are hand-written under src/chart/). So:
no `dependencies`, every lock entry dev-only from the registry with an integrity hash,
install scripts only where the toolchain needs them, CI installs with --ignore-scripts,
and the shipped code imports nothing but svelte and the face's own files.
"""
from __future__ import annotations

import gzip
import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PUPIL = REPO / "files/anatomy/pupil"
FACE = REPO / "files/anatomy/face/src"  # vite.config.ts `$face`; `$lib` is its lib, `$iris` lib/iris
BORROWED = ("$face/", "$lib/", "$iris/")
CI = REPO / ".github/workflows/ci.yml"
#: the toolchain's native binaries; both are devDependencies (lock `dev: true`)
INSTALL_SCRIPTS_OK = {"esbuild", "fsevents"}
IMPORT = re.compile(r"""\bfrom\s*(['"])([^'"\n]+)\1|\bimport\s*\(?\s*(['"])([^'"\n]+)\3""")
#: gzip -9 of dist/assets/*.js measured 26 950 B on dev @ 49904f43 (2026-10-13), plus 60 KiB
#: for the hand-written chart, timeline, graph, form and workspace code of I5b-I5h.
JS_GZIP_CEILING = 27_000 + 60 * 1024
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(")
#: the eye is a drawn object (glass, bezel, glow), not a renderer of model data
FIXED_COLOUR = {"Eye.svelte"}


def _lock_strays(lock: dict) -> list[str]:
    bad = []
    for path, p in lock["packages"].items():
        if not path:
            continue
        name = path.rsplit("node_modules/", 1)[-1]
        if p.get("dev") is not True:
            bad.append(f"{name}: not dev-only (a runtime package)")
        if not p.get("integrity") or not p.get("resolved", "").startswith("https://registry.npmjs.org/"):
            bad.append(f"{name}: no integrity, or not from registry.npmjs.org")
        if p.get("hasInstallScript") and name not in INSTALL_SCRIPTS_OK:
            bad.append(f"{name}: has an install script")
    return bad


def _specifiers(text: str) -> list[str]:
    return [m[2] or m[4] for m in IMPORT.finditer(text)]


def _resolve(spec: str, here: pathlib.Path) -> pathlib.Path | None:
    if spec.startswith("."):
        base = here.parent / spec
    elif spec.startswith("$lib/"):
        base = FACE / "lib" / spec[5:]
    elif spec.startswith("$iris/"):
        base = FACE / "lib/iris" / spec[6:]
    elif spec.startswith("$face/"):
        base = FACE / spec[6:]
    else:
        return None
    return next((p for p in (base, base.with_name(base.name + ".ts"), base / "index.ts")
                 if p.is_file() and p.suffix in {".ts", ".js", ".svelte"}), None)


def _bare_imports() -> dict[str, set[str]]:
    """{bare specifier: files} over the shipped pupil code and every face file it reaches."""
    todo = [p for ext in ("ts", "js", "svelte") for p in (PUPIL / "src").rglob(f"*.{ext}")
            if not p.name.endswith(".test.ts")]
    seen, bare = set(), {}
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        for spec in _specifiers(f.read_text(encoding="utf-8")):
            if spec.startswith((".", *BORROWED)):
                if (hit := _resolve(spec, f)) is not None:
                    todo.append(hit)
            bare.setdefault(spec, set()).add(str(f.relative_to(REPO)))
    return bare


def _not_allowed(spec: str) -> bool:
    return not (spec.startswith((".", *BORROWED, "svelte/")) or spec == "svelte")


def test_the_pupil_has_no_runtime_dependencies():
    pkg = json.loads((PUPIL / "package.json").read_text(encoding="utf-8"))
    assert pkg.get("dependencies", {}) == {}, f"runtime deps (hand-write it under src/chart/): {pkg['dependencies']}"
    pins = pkg.get("devDependencies", {})
    assert all(re.fullmatch(r"\d+\.\d+\.\d+", v) for v in pins.values()), f"a devDependency is not an exact pin: {pins}"


def test_every_lock_entry_is_a_dev_tool_from_the_registry():
    lock = json.loads((PUPIL / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["lockfileVersion"] == 3 and len(lock["packages"]) > 1, "the lock was not read"
    assert not _lock_strays(lock)


def test_a_planted_lock_entry_goes_red():
    planted = {"packages": {"": {}, "node_modules/evil": {
        "resolved": "https://registry.npmjs.org/evil/-/evil-1.0.0.tgz", "integrity": "sha512-x", "hasInstallScript": True}}}
    assert _lock_strays(planted) == ["evil: not dev-only (a runtime package)", "evil: has an install script"]


def test_the_shipped_code_imports_only_svelte_and_the_face():
    bare = _bare_imports()
    assert "svelte" in bare and any(s.startswith("$lib/components/ui/") for s in bare), f"the import scan saw nothing: {sorted(bare)}"
    bad = {s: sorted(f) for s, f in bare.items() if _not_allowed(s)}
    assert not bad, f"an import outside svelte, $face/*, $lib/*, $iris/*: {bad}"


def test_a_planted_import_goes_red():
    for text in ("import 'd3-selection';", 'import { x } from "d3-scale";', "const m = await import('lodash');",
                 "export * from 'left-pad';", "import {\n\ta,\n\tb\n} from 'chart.js';"):
        assert [s for s in _specifiers(text) if _not_allowed(s)], text
    assert not [s for s in _specifiers("import { mount } from 'svelte';\nimport '$face/app.css';") if _not_allowed(s)]


def test_ci_installs_the_pupil_without_running_scripts():
    lines = [ln for ln in CI.read_text(encoding="utf-8").splitlines() if "npm ci" in ln and "files/anatomy/pupil" in ln]
    assert lines, "ci.yml has no `npm ci` for the pupil"
    assert all("--ignore-scripts" in ln for ln in lines), f"the pupil install runs package scripts: {lines}"


def test_the_pupil_draws_colour_through_tokens():
    svelte = sorted([*(PUPIL / "src").rglob("*.svelte"), *(FACE / "lib/iris").rglob("*.svelte")])
    assert any(p.name == "Component.svelte" and p.is_relative_to(FACE) for p in svelte), "the colour scan does not see Iris"
    bad = [f"{p.name}: {m}" for p in svelte if p.name not in FIXED_COLOUR
           for m in COLOUR.findall(p.read_text(encoding="utf-8"))]
    assert not bad, f"a colour literal (use a var(--…) token, so the dark theme holds): {bad}"
    assert COLOUR.findall('fill="#fff"') and COLOUR.findall("color: rgb(0 0 0)") and not COLOUR.findall("url(#eye-glow)")


@pytest.mark.skipif(not shutil.which("npx"), reason="npx runs vite")
def test_the_bundle_stays_under_its_budget(tmp_path):
    assert (PUPIL / "node_modules").is_dir(), "run `npm ci --ignore-scripts` in files/anatomy/pupil first"
    r = subprocess.run(["npx", "vite", "build", "--outDir", str(tmp_path), "--emptyOutDir"], cwd=PUPIL,
                       capture_output=True, text=True, timeout=600, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    js = list(tmp_path.rglob("*.js"))
    total = sum(len(gzip.compress(p.read_bytes(), 9)) for p in js)
    assert js and total < JS_GZIP_CEILING, f"gzip JS {total} B over {JS_GZIP_CEILING} B: {[p.name for p in js]}"
