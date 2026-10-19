"""The pytest lane runs as parallel CI jobs, and together they run every test once.

One serial pytest job set the whole CI wall-clock (17-25 min, 2026-10-15). It is
split across a matrix of runners by `tests/_shard.py` (NOS_PYTEST_SHARD=k/N,
whole files, balanced by tests/_weights.json). A split that loses a file is a quiet
green, so this gate partitions the real anatomy collection with the CI's own N, and
drives the real conftest hook per shard. The anatomy collection is read from this
session when it collected all of tests/anatomy, else from a --collect-only subprocess. The required check keeps its name on
an aggregate job that is red unless every shard was green.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import subprocess
import sys
from collections import Counter

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CI = REPO / ".github" / "workflows" / "ci.yml"
SHARD_MODULE = REPO / "tests" / "_shard.py"
CHECK_NAME = "Pytest (Python tests)"


def _jobs() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]


def _shard_count() -> int:
    job = _jobs()["pytest"]
    shards = ((job.get("strategy") or {}).get("matrix") or {}).get("shard")
    assert shards, "the pytest job has no `strategy.matrix.shard`: it still runs serially on one runner"
    n = len(shards)
    assert n >= 2 and shards == list(range(1, n + 1)), f"matrix.shard must be 1..N, got {shards}"
    return n


def _collect(target: str, shard: str | None) -> list[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("NOS_TEST_PROVIDES", "NOS_PYTEST_SHARD")}
    if shard:
        env["NOS_PYTEST_SHARD"] = shard
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--collect-only", "-q", target],
        capture_output=True, text=True, timeout=300, cwd=REPO, env=env,
    )
    assert r.returncode in ((0, 5) if shard else (0,)), f"collect-only of {target} (shard={shard}) failed:\n{r.stdout[-2000:]}{r.stderr[-2000:]}"
    return [line for line in r.stdout.splitlines() if "::" in line]


def _exactly_once(full: list[str], parts: list[list[str]]) -> None:
    seen = Counter(n for part in parts for n in part)
    twice = sorted(n for n, c in seen.items() if c > 1)
    lost = sorted(set(full) - set(seen))
    extra = sorted(set(seen) - set(full))
    assert not (twice or lost or extra), f"twice={twice[:5]} lost={lost[:5]} invented={extra[:5]}"


def test_ci_runs_the_pytest_job_as_a_shard_matrix():
    n = _shard_count()
    job = _jobs()["pytest"]
    assert job["strategy"].get("fail-fast") is False, "fail-fast would cancel shards and hide their reds"
    assert str((job.get("env") or {}).get("NOS_PYTEST_SHARD")) == f"${{{{ matrix.shard }}}}/{n}"
    runs = "\n".join(str(s.get("run", "")) for s in job["steps"])
    assert "python3 -m pytest tests/" in runs, "each shard must run the same scope the serial job ran"


def test_the_required_check_is_an_aggregate_of_every_shard():
    gates = [j for j in _jobs().values() if j.get("name") == CHECK_NAME]
    assert len(gates) == 1, f"exactly one job must carry the check name {CHECK_NAME!r}"
    gate = gates[0]
    needs = gate.get("needs")
    assert needs == "pytest" or "pytest" in (needs or []), "the aggregate must wait for the shards"
    assert "always()" in str(gate.get("if", "")), "without if: always() a red shard SKIPS the check, and skipped passes"
    runs = "\n".join(str(s.get("run", "")) for s in gate["steps"])
    assert re.search(r"needs\.pytest\.result\s*\}\}\"?\s*=\s*\"?success", runs), "the aggregate must fail unless needs.pytest.result is success"


def test_the_shards_collect_every_anatomy_test_exactly_once(pytestconfig):
    n = _shard_count()
    assert SHARD_MODULE.is_file(), "tests/_shard.py (the split) does not exist"
    spec = importlib.util.spec_from_file_location("_nos_shard", SHARD_MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import _shard
    full = _shard.collected_under(pytestconfig, "tests/anatomy") or _collect("tests/anatomy", None)
    assert len(full) > 1000, f"anatomy collected only {len(full)} tests"
    plan = mod.assign(full, n)
    _exactly_once(full, [[x for x in full if plan[x.split("::")[0]] == k] for k in range(1, n + 1)])


def test_the_conftest_hook_deselects_to_the_same_partition():
    n = _shard_count()
    full = _collect("tests/apps", None)
    assert full, "tests/apps collected nothing"
    _exactly_once(full, [_collect("tests/apps", f"{k}/{n}") for k in range(1, n + 1)])
