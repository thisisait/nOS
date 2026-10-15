"""A bare `pip3 install` runs only after actions/setup-python in its job.

ubuntu-24.04's system Python is PEP 668 externally-managed: a bare pip3 there
exits `externally-managed-environment`, and every job `needs:`-ing it is skipped.
"""
import pathlib
import re

import pytest
import yaml

WORKFLOWS = sorted((pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows").glob("*.yml"))
BARE_PIP = re.compile(r"(?m)^\s*(?:[^#\n]*&&\s*)?pip3? install")


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_bare_pip_follows_setup_python(wf):
	bad = []
	for name, job in (yaml.safe_load(wf.read_text()).get("jobs") or {}).items():
		has_python = False
		for step in job.get("steps") or []:
			if str(step.get("uses", "")).startswith("actions/setup-python"):
				has_python = True
			if BARE_PIP.search(str(step.get("run", ""))) and not has_python:
				bad.append(f"{name}: {step.get('name')}")
	assert not bad, f"{wf.name}: bare pip install before actions/setup-python: {bad}"
