"""BindingResolver finds the backend register at state/habitat/, and at the old
state/ path while a checkout still has only that.

WHY (repo-body-plan I-11, 2026-10-07). The register moved to state/habitat/.
Wing reads it through NOS_REPO_ROOT, and a missing file reads as an EMPTY
register (no backend resolves), not as an error. Drop the old-path case when
the compat read is removed after every host's `--tags wing` converge.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
AUTOLOAD = REPO / "files/anatomy/wing/vendor/autoload.php"
PROBE = (
    "require $argv[1]; echo json_encode(array_keys("
    "App\\AgentKit\\LLMClient\\BindingResolver::readRegistry()));"
)


def _rows(root: Path) -> list[str]:
    php = shutil.which("php")
    out = subprocess.run([php, "-r", PROBE, str(AUTOLOAD)], capture_output=True, text=True,
                         timeout=60, env={"NOS_REPO_ROOT": str(root), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr[-500:]
    return json.loads(out.stdout)


@pytest.fixture
def register_text():
    if shutil.which("php") is None or not AUTOLOAD.is_file():
        pytest.skip("php or wing vendor/autoload.php missing — composer install in files/anatomy/wing")
    return (REPO / "state/habitat/llm-backends.yml").read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", ["state/habitat/llm-backends.yml", "state/llm-backends.yml"])
def test_the_register_is_found(tmp_path, register_text, rel):
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text(register_text)
    assert "anthropic" in _rows(tmp_path)


def test_no_register_is_empty_not_a_crash(tmp_path, register_text):
    assert _rows(tmp_path) == []
