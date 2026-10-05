"""Every converge in a CI job carries the `-e` flags of that job's first one.

The first converge declares the job's sandbox (allow_weak_prefix: a runner has
no credentials.yml; nos_allow_no_docker; interpreter pins). The macOS
idempotence pass dropped allow_weak_prefix, so the prefix assert stopped it at
task 96 (run 37368276781) — red for the step, not for idempotence.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CI = REPO / ".github" / "workflows" / "ci.yml"


def _extra_vars(run: str) -> set[str]:
    return set(re.findall(r"-e\s+['\"]?(\w+)=", run))


def _converges(job: dict) -> list[tuple[str, str]]:
    return [(s.get("name", "?"), str(s["run"])) for s in job.get("steps", [])
            if "ansible-playbook main.yml" in str(s.get("run", ""))
            and "--syntax-check" not in str(s["run"])]


def test_extra_var_reader() -> None:
    assert _extra_vars('ansible-playbook main.yml -e a=true \\\n  -e b="${{ x }}"') == {"a", "b"}


def test_every_converge_carries_the_first_converges_flags() -> None:
    jobs = yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]
    drift = []
    for name, job in jobs.items():
        steps = _converges(job)
        if not steps:
            continue
        first = _extra_vars(steps[0][1])
        drift += [f"{name} / {step}: missing {sorted(first - _extra_vars(run))}"
                  for step, run in steps[1:] if first - _extra_vars(run)]
    assert not drift, "a later converge runs outside the job's sandbox:\n" + "\n".join(drift)
