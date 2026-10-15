"""NOS_PYTEST_SHARD=k/N keeps only shard k of N, split by whole test file.

Files go greedily (most tests first, ties by path) to the lightest shard, so
every runner computes the same plan from the same checkout. Pinned by
tests/anatomy/test_pytest_lane_is_sharded_and_complete.py.
"""
from __future__ import annotations

import os
import re
from collections import Counter

import pytest

ENV = "NOS_PYTEST_SHARD"


def assign(nodeids, n: int) -> dict[str, int]:
    # ponytail: balanced by test COUNT; weigh by recorded durations once CI keeps a junit artifact.
    counts = Counter(nid.split("::")[0] for nid in nodeids)
    load, plan = [0] * n, {}
    for path, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        k = load.index(min(load))
        plan[path], load[k] = k + 1, load[k] + c
    return plan


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    spec = os.environ.get(ENV, "").strip()
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
