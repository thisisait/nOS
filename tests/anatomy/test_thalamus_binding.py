"""The thalamus binds its cell (iris) the way BindingResolver.php binds Wing's.

WHY. The thalamus runs a model without Wing, so it resolves the binding itself.
A second resolver that drifted from the first would route a person's rows to a
backend the cell's Article-30 record does not cover. The Rust cases read the
REAL register and the real iris cell, so a register edit moves both resolvers.
CI runs pytest, not cargo, so this file runs `cargo test --test binding`.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CRATE = REPO / "files/anatomy/thalamus/thalamus"
IRIS = REPO / "files/anatomy/agents/iris/agent.yml"
REGISTER = REPO / "state/habitat/llm-backends.yml"


def test_the_iris_cell_binds_to_the_eu_row_alone():
    """Ruling 2026-10-12 (supersedes ruling 4's ollama): iris binds mistral-eu, and nothing outside the EU serves it."""
    doc = yaml.safe_load(IRIS.read_text())
    assert doc["name"] == "iris"
    assert doc["model"]["backend"] == "mistral-eu"
    assert doc["gdpr"]["transfers_outside_eu"] is False, (
        "without it a disarmed mistral-eu degrades iris to the hosted default")
    tier = re.search(r"\b(haiku|sonnet|opus|vision)\b", doc["model"]["primary"])
    spec = yaml.safe_load(REGISTER.read_text())["backends"]["mistral-eu"]
    assert tier and spec["model_env"].get(tier[1]), f"{doc['model']['primary']} has no model on mistral-eu"
    assert spec["residency"]["eu"] is True
    names = [p["name"] for p in doc["gdpr"]["processors"]]
    assert names and all(spec["processor_match"] in n for n in names), (
        f"every processor iris names must be the EU row's, got {names}")


def test_the_rust_cases_read_the_register_not_a_copy():
    src = (CRATE / "tests/binding.rs").read_text()
    assert "state/habitat/llm-backends.yml" in src
    assert not list(CRATE.rglob("llm-backends*.yml")), "a copied register drifts from the real one"


@pytest.mark.skipif(not shutil.which("cargo"), reason="cargo runs the resolver")
def test_the_resolver_runs():
    r = subprocess.run(["cargo", "test", "--quiet", "--manifest-path", str(CRATE / "Cargo.toml"),
                        "--test", "binding"], capture_output=True, text=True, timeout=600, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    n = re.search(r"(\d+) passed", r.stdout)
    assert n and int(n[1]) >= 13, r.stdout
