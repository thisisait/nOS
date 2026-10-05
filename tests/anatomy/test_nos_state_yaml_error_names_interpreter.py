"""nos_state's missing-PyYAML error names the interpreter that ran it.

macOS CI fails `[pre-migrate] Read current state` with "PyYAML is required"
while the job's own check proves $PY imports yaml — so another interpreter
ran the module, and the message never said which. Now it does.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "files" / "anatomy" / "module_utils"))
import nos_state_lib  # noqa: E402


def test_missing_yaml_error_names_the_interpreter(monkeypatch) -> None:
    monkeypatch.setattr(nos_state_lib, "yaml", None)
    with pytest.raises(RuntimeError) as exc:
        nos_state_lib._require_yaml()
    assert f"interpreter={sys.executable}" in str(exc.value)
