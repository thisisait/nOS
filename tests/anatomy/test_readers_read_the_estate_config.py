"""Readers resolve the operator's config.yml from the estate clone, not the dev tree.

2026-10-24: since the estate split (row estate-dev-split) the converge reads
~/.nos/estate/config.yml, but `estate-status --config` run from the dev tree
read ~/projects/nOS/config.yml, a copy frozen at the split, and printed
"config.yml does not override it" for flags the estate does override.
One helper, nos_identity.operator_file, answers for every reader.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402


def _estate(tmp_path: Path, monkeypatch) -> Path:
    est = tmp_path / "estate"
    est.mkdir()
    subprocess.run(["git", "init", "-q", str(est)], check=True)
    (est / "config.yml").write_text("install_zz_probe: true\n")
    monkeypatch.setenv("NOS_ESTATE_DIR", str(est))
    return est


def test_the_estate_config_is_the_operator_file(tmp_path, monkeypatch):
    est = _estate(tmp_path, monkeypatch)
    assert ni.operator_file("config.yml") == est / "config.yml"


def test_a_flag_resolves_through_the_estate_config(tmp_path, monkeypatch):
    _estate(tmp_path, monkeypatch)
    assert ni.resolve_flag("install_zz_probe")[-1][1] == "true"


def test_without_an_estate_the_checkout_answers(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_ESTATE_DIR", str(tmp_path / "none"))
    assert ni.operator_file("config.yml").parent != tmp_path / "none"
