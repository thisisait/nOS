"""The macOS wet-test pins the interpreter our python3-shebang modules use.

Measured (ansible-core 2.20/2.21 executor/module_common.py `_get_shebang`): a
custom module's OWN shebang picks the pin variable. `#!/usr/bin/python` obeys
`ansible_python_interpreter`; `#!/usr/bin/python3` (nos_state, nos_migrate,
nos_authentik, nos_secret_map) only obeys `ansible_python3_interpreter`, else it
runs /usr/bin/python3 verbatim. On the macOS runner that is Apple's 3.9, whose
pyyaml the preflight lands in --user site, which the job's PYTHONNOUSERSITE=1
hides: "PyYAML is required for nos_state_lib" since 2026-06-08, 7 fixes deep.

Pinned: while any library module carries the python3 shebang, every converge
in the macOS `integration` job passes ansible_python3_interpreter, and $PY gets
requests (nos_authentik's hard dep).
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
LIB = REPO / "files" / "anatomy" / "library"
CI = REPO / ".github" / "workflows" / "ci.yml"


def _python3_modules() -> list[str]:
    return [p.name for p in sorted(LIB.glob("*.py"))
            if p.read_text(encoding="utf-8").startswith("#!/usr/bin/python3")]


def _macos_runs() -> list[str]:
    job = yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]["integration"]
    return [str(s.get("run", "")) for s in job["steps"]]


def test_every_macos_converge_pins_python3() -> None:
    if not _python3_modules():
        return
    converges = [r for r in _macos_runs() if "ansible-playbook main.yml" in r and "--syntax-check" not in r]
    assert converges, "macOS integration job has no converge step"
    for run in converges:
        assert "ansible_python3_interpreter" in run, (
            f"{_python3_modules()} carry #!/usr/bin/python3 — without "
            "-e ansible_python3_interpreter they run on Apple's /usr/bin/python3:\n" + run
        )


def test_py_gets_requests() -> None:
    assert any('pip install' in r and "requests" in r for r in _macos_runs()), (
        "nos_authentik imports requests; $PY must have it once modules run there"
    )
