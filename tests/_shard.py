"""NOS_PYTEST_SHARD=k/N keeps only shard k of N, split by whole test file.

Files go greedily (heaviest first, ties by path) to the lightest shard, so
every runner computes the same plan from the same checkout. A file weighs its
measured seconds from tests/_weights.json; a file with no record weighs
`per_test_default` seconds per test. Pinned by
tests/anatomy/test_pytest_lane_is_sharded_and_complete.py.

Refresh the weights from one or more `pytest --durations=0` logs:
    python3 -m pytest tests -q -p no:cacheprovider --durations=0 > /tmp/d.log
    python3 tests/_shard.py /tmp/d.log
"""
from __future__ import annotations

import functools
import json
import os
import pathlib
import re
import subprocess
import sys
from collections import Counter, defaultdict

import pytest

ENV = "NOS_PYTEST_SHARD"
WEIGHTS = pathlib.Path(__file__).with_name("_weights.json")
# ponytail: weights measured on the dev host; refresh from CI shard logs when the shard walls drift apart.
FLOOR_S = 0.5  # files cheaper than this are not recorded; they weigh per_test_default per test


def _weights() -> dict:
    try:
        return json.loads(WEIGHTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # no weights = balanced by count (per_test_default 1)


def assign(nodeids, n: int, weights: dict | None = None) -> dict[str, int]:
    w = _weights() if weights is None else weights
    files, per_test = w.get("files", {}), w.get("per_test_default", 1.0)
    counts = Counter(nid.split("::")[0] for nid in nodeids)
    cost = {p: files.get(p, c * per_test) for p, c in counts.items()}
    load, plan = [0.0] * n, {}
    for path in sorted(cost, key=lambda p: (-cost[p], p)):
        k = load.index(min(load))
        plan[path], load[k] = k + 1, load[k] + cost[path]
    return plan


COLLECTED: list[str] | None = None  # this session's whole collection, before the shard cut
ALL: list[str] | None = None  # the same, before the tests/_lanes.yml cut too (set by tests/conftest.py)


def collected_under(config, rel: str) -> list[str] | None:
    """Nodeids this session collected under `rel`, or None when it did not collect all of it
    (a narrower path, -k/-m/--deselect/--lf/--ignore): collection() then collects in a subprocess."""
    o = config.option
    if COLLECTED is None or any(getattr(o, a, None) for a in ("keyword", "markexpr", "deselect", "lf", "ignore", "ignore_glob")):
        return None
    target = (config.rootpath / rel).resolve()
    here = config.invocation_params.dir
    if not any("::" not in a and (target == (here / a).resolve() or (here / a).resolve() in target.parents)
               for a in config.args):
        return None
    return _under(COLLECTED, rel)


def _under(nodeids: list[str], rel: str) -> list[str]:
    return [n for n in nodeids if n.startswith(rel.rstrip("/") + "/")]


@functools.cache
def _collect_only(root: str, rel: str) -> tuple[tuple[str, ...], int]:
    env = {k: v for k, v in os.environ.items() if k not in ("NOS_TEST_PROVIDES", ENV)}
    r = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--collect-only", "-q", rel],
                       capture_output=True, text=True, timeout=600, cwd=root, env=env)
    m = re.search(r"(\d+)(?:/(\d+))?\s+tests? collected", r.stdout)
    assert r.returncode == 0 and m, f"collect-only of {rel} failed (rc={r.returncode}):\n{r.stdout[-2000:]}{r.stderr[-2000:]}"
    return tuple(ln for ln in r.stdout.splitlines() if "::" in ln), int(m[2] or m[1])


def collection(config, rel: str) -> tuple[list[str], int]:
    """(nodeids selected under `rel` with this env's NOS_LANE, count collected before the lane cut).
    From this session's own collection when it covered `rel`, else ONE --collect-only
    subprocess per session, shared by every gate that asks (gate-diet, 2026-11-08)."""
    selected = collected_under(config, rel)
    if selected is not None and ALL is not None:
        return selected, len(_under(ALL, rel))
    nodeids, total = _collect_only(str(config.rootpath), rel)
    return list(nodeids), total


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    global COLLECTED
    COLLECTED = [i.nodeid for i in items]
    spec = os.environ.pop(ENV, "").strip()  # read once: a pytest a test spawns must not inherit it
    if not spec:
        return
    m = re.fullmatch(r"(\d+)/(\d+)", spec)
    if not m or not 1 <= int(m[1]) <= int(m[2]):
        raise pytest.UsageError(f"{ENV}={spec!r}: expected k/N with 1 <= k <= N")
    k, n = int(m[1]), int(m[2])
    plan = assign([i.nodeid for i in items], n)
    keep, drop = [], []
    for i in items:
        (keep if plan[i.nodeid.split("::")[0]] == k else drop).append(i)
    config.hook.pytest_deselected(items=drop)
    items[:] = keep


DURATION = re.compile(r"^\s*([\d.]+)s (?:setup|call|teardown)\s+(\S+?\.py)::")


def refresh(logs: list[str]) -> dict:
    """Sum every setup/call/teardown line per file; record files >= FLOOR_S."""
    per_file = defaultdict(float)
    for log in logs:
        for line in pathlib.Path(log).read_text(encoding="utf-8", errors="replace").splitlines():
            if m := DURATION.match(line):
                per_file[m[2]] += float(m[1])
    assert per_file, f"no --durations lines in {logs}: run pytest with --durations=0"
    return {
        "_doc": "per-file seconds for tests/_shard.py; refresh: python3 tests/_shard.py <durations.log>...",
        "per_test_default": 0.01,  # 2026-10-19: 5869 tests in unrecorded files ran 57 s
        "files": {p: round(s, 1) for p, s in sorted(per_file.items()) if s >= FLOOR_S},
    }


if __name__ == "__main__":
    WEIGHTS.write_text(json.dumps(refresh(sys.argv[1:]), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {WEIGHTS}")
