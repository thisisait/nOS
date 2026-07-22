"""If a version is pinned and then asserted, the fetch must use that pin.

CI 2026-07-22: `roles/pazny.wing` downloaded FrankenPHP from
`releases/latest/download/…` on Linux and then failed the run because the
binary did not report `frankenphp_version` (1.12.4 pinned, 1.12.6 fetched).
The two statements could only agree by luck, and upstream cutting a release
ended the luck. macOS was unaffected — its version comes from the brew formula,
which still had the pinned one — so the defect was invisible on the operator's
machine and deterministic in CI.

The rule: **a pin that does not govern the fetch pins nothing.** Where a task
downloads an artifact whose version is later asserted, the URL must be built
from the same variable that the assertion reads. `latest` is not a version.

This is the sibling of the pin-shadow trap in memory
`version-pins-default-config-shadow` (a pin in two places, the wrong one bumped):
here the pin exists in one place and simply has no authority over anything.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]

# (task file, the version var it pins, a URL fragment identifying the fetch)
PINNED_FETCHES = [
    (pathlib.Path("roles/pazny.wing/tasks/main.yml"), "frankenphp_version", "frankenphp"),
]


def _tasks(path: pathlib.Path):
    out = []

    def walk(items):
        for t in items or []:
            if not isinstance(t, dict):
                continue
            out.append(t)
            for key in ("block", "rescue", "always"):
                if key in t:
                    walk(t[key])

    walk(yaml.safe_load((REPO / path).read_text()))
    return out


def _get_url_tasks(path: pathlib.Path):
    for t in _tasks(path):
        mod = t.get("get_url") or t.get("ansible.builtin.get_url")
        if mod:
            yield t, str(mod.get("url", ""))


def test_pinned_downloads_do_not_fetch_latest():
    for path, var, fragment in PINNED_FETCHES:
        assert (REPO / path).is_file(), f"{path} is gone — move this gate with it"
        for task, url in _get_url_tasks(path):
            if fragment not in url:
                continue
            assert "/latest/" not in url, (
                f"{path}: task {task.get('name')!r} fetches `latest` while the "
                f"run asserts the artifact equals {{{{ {var} }}}}. Upstream's "
                "next release breaks it, and only on the platform that uses "
                "this URL. Build the URL from the pin."
            )
            assert var in url, (
                f"{path}: task {task.get('name')!r} downloads the artifact "
                f"without referencing {var}, the variable its own preflight "
                "asserts. The pin has no authority over the fetch."
            )


def test_the_asserted_pin_still_exists_as_a_real_default():
    """The var must be defined where the eager-resolve namespace can see it."""
    cfg = (REPO / "default.config.yml").read_text()
    for _, var, _ in PINNED_FETCHES:
        assert re.search(rf"^{re.escape(var)}\s*:", cfg, re.M), (
            f"{var} has no definition in default.config.yml — the URL now "
            "depends on it, so an undefined value would break the fetch "
            "itself, not just the assertion"
        )
