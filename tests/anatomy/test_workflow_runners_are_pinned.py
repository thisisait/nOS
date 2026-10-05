"""Every GitHub workflow runs on a pinned runner image, never `*-latest`.

`ubuntu-latest` moves to Ubuntu 26 from 2026-10-19 (GitHub's own annotation on
our CI); nOS supports Ubuntu 24.04, so a floating label changes the platform
under a green build without a commit. Parsed, not grepped: `runs-on` and every
matrix value it expands to are read from the YAML.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.y*ml"))


def _labels(job: dict) -> list[str]:
    runs_on = job.get("runs-on", [])
    labels = runs_on if isinstance(runs_on, list) else [runs_on]
    out: list[str] = []
    matrix = (job.get("strategy") or {}).get("matrix") or {}
    for label in map(str, labels):
        ref = re.fullmatch(r"\$\{\{\s*matrix\.(\w+)\s*\}\}", label)
        if ref:
            values = matrix.get(ref.group(1), [])
            out += [str(v) for v in values] + [
                str(i.get(ref.group(1))) for i in matrix.get("include", []) if ref.group(1) in i
            ]
        else:
            out.append(label)
    return out


def test_there_are_workflows_to_check() -> None:
    assert WORKFLOWS, ".github/workflows has no workflow files"


def test_no_runner_label_floats() -> None:
    floating = [
        f"{wf.name}:{name} runs-on {label}"
        for wf in WORKFLOWS
        for name, job in (yaml.safe_load(wf.read_text(encoding="utf-8")).get("jobs") or {}).items()
        for label in _labels(job)
        if label.endswith("-latest")
    ]
    assert not floating, "pin the runner image (e.g. ubuntu-24.04):\n" + "\n".join(floating)


def test_the_matrix_reader_sees_latest() -> None:
    job = {"runs-on": "${{ matrix.os }}", "strategy": {"matrix": {"os": ["macos-15"], "include": [{"os": "ubuntu-latest"}]}}}
    assert _labels(job) == ["macos-15", "ubuntu-latest"]
