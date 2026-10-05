"""Gate: the self-model generator cortex spawns as `python3` resolves to the
nOS tools venv (PyYAML), not to whatever the host's PATH offers.

macOS-15 Integration 2026-10-05: no pyenv shim on the runner, Homebrew python3
without yaml → `store:materialise` died in keap_selfmodel_gen.py (`import yaml`).
"""
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def test_materialise_path_puts_the_tools_venv_before_any_host_python():
    task = next(t for t in yaml.safe_load((REPO / "roles/pazny.cortex/tasks/main.yml").read_text())
                if "Materialise the store" in t.get("name", ""))
    parts = task["environment"]["PATH"].split(":")
    venv = parts.index("{{ nos_tools_venv }}/bin")
    hosts = [i for i, p in enumerate(parts) if "pyenv" in p or "homebrew" in p or p.startswith("/usr")]
    assert all(venv < i for i in hosts), parts


def test_the_tools_venv_carries_pyyaml_and_is_built_before_cortex():
    assert any(ln.lower().startswith("pyyaml") for ln in (REPO / "tools/requirements.txt").read_text().splitlines())
    main = (REPO / "main.yml").read_text()
    assert main.index("tasks/tools-venv.yml") < main.index("name: pazny.cortex")
