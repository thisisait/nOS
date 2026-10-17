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


def test_the_iris_cell_binds_to_the_eu_row_by_default():
    """Ruling 2026-10-12: iris binds mistral-eu. Ruling 2026-10-14: a host may choose the on-device row
    instead (iris_backend: ollama) — chosen explicitly, never as a fallback. Ruling 2026-10-17: also the
    non-EU anthropic-api / minimax-api rows, which gate 8 serves only at gdpr_posture: none."""
    doc = yaml.safe_load(IRIS.read_text())
    assert doc["name"] == "iris"
    assert doc["model"]["backend"] == "mistral-eu"
    assert doc["model"]["backends_allowed"] == ["mistral-eu", "ollama", "anthropic-api", "minimax-api"]
    non_eu = {"anthropic-api", "minimax-api"}
    assert doc["gdpr"]["transfers_outside_eu"] is False, (
        "without it a disarmed mistral-eu degrades iris to the hosted default")
    tier = re.search(r"\b(haiku|sonnet|opus|vision)\b", doc["model"]["primary"])
    rows = yaml.safe_load(REGISTER.read_text())["backends"]
    for b in doc["model"]["backends_allowed"]:
        assert tier and rows[b]["model_env"].get(tier[1]), f"{doc['model']['primary']} has no model on {b}"
        assert rows[b]["residency"]["eu"] is (b not in non_eu), f"{b}: residency is not what the ruling says"
    names = [p["name"] for p in doc["gdpr"]["processors"]]
    for b in doc["model"]["backends_allowed"]:
        assert any(rows[b]["processor_match"] in n for n in names), f"no processor of iris names the {b} row"
    assert all(any(rows[b]["processor_match"] in n for b in doc["model"]["backends_allowed"]) for n in names), (
        f"every processor iris names must belong to an allowed row, got {names}")


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
