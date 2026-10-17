"""The thalamus's plan mapper pins the cortex registry it was written against, by hash.

WHY THIS GATE EXISTS. `cortex_plan.rs` refuses every plan whose AST carries another
`opcodeRegistryHash` (validate(): "registry ... is not the one this mapper was built
for"), and serve then falls back to plain tool calling - quietly, every turn. The pin
was copied by hand into three places (the Rust constant, this suite's HASH, the
cortex-plan fixture), and the gates that use it answer with a fake organ that echoes
the pin back, so a registry change in cortex-opcodes.ts would leave every gate green
while Iris never planned again. This reads the hash the organ itself computes.

It runs the registry module with node's type stripping: cortex-opcodes.ts imports
only node:crypto, so no node_modules are needed.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CORTEX = REPO / "files/anatomy/cortex"
MAPPER = REPO / "files/anatomy/thalamus/thalamus/src/cortex_plan.rs"


def _organ_hash() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent — the registry hash is computed by the organ's own module")
    js = "import('./server/cortex-opcodes.ts').then(m => console.log(m.cortexRegistryHash()))"
    done = subprocess.run([node, "--experimental-strip-types", "--no-warnings", "-e", js],
                          capture_output=True, text=True, cwd=CORTEX, timeout=60)
    assert done.returncode == 0, done.stderr[-600:]
    return done.stdout.strip()


def test_the_mapper_pins_the_hash_the_organ_computes():
    organ = _organ_hash()
    assert re.fullmatch(r"cx1:[0-9a-f]{16}", organ), organ
    pinned = re.search(r'pub const REGISTRY_HASH: &str = "([^"]+)";', MAPPER.read_text(encoding="utf-8"))
    assert pinned, "no REGISTRY_HASH in cortex_plan.rs"
    assert pinned.group(1) == organ, (
        f"cortex_plan.rs pins {pinned.group(1)}, the organ computes {organ}: every Iris plan is refused "
        "until the mapper is checked against the new registry and the pin moved")


def test_every_copy_of_the_pin_is_the_organs():
    organ = _organ_hash()
    bench = re.search(r'^HASH = "([^"]+)"', (REPO / "tests/anatomy/test_iris_bench_pipeline.py").read_text(encoding="utf-8"), re.M)
    assert bench and bench.group(1) == organ
    cases = yaml.safe_load((REPO / "state/fixtures/cortex-plan/cases.yml").read_text(encoding="utf-8"))["cases"]
    # one case pins a registry on purpose, to be refused: it is all zeros
    pins = {c["registry_hash"] for c in cases if "registry_hash" in c}
    assert pins <= {"cx1:0000000000000000"}, pins
