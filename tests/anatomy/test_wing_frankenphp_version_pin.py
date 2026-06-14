"""Anatomy gate — FrankenPHP version is pinned AND preflight-validated.

darwin27-frankenphp-binary-compatibility (2026-06):

Wing's host runtime is the FrankenPHP single binary, installed via the
`dunglas/frankenphp` Homebrew tap on macOS (and a GitHub static binary on
Linux). The install path is architecture-agnostic — one ARM64 binary serves
every Apple Silicon generation (M1..M5), there are NO per-chip sub-variants.
The real gap is process discipline:

  1. an UNPINNED version drifts silently across runs, and
  2. a half-finished source build (no arm64_sequoia bottle on older macOS) or a
     missing/partial download leaves the launchd daemon to segfault.

This gate pins both halves of the fix:

  - `default.config.yml` declares `frankenphp_version` as a plain
    MAJOR.MINOR.PATCH literal (stock-Jinja safe — no filter, no template).
  - `roles/pazny.wing/tasks/main.yml` reads `frankenphp --version` and refuses
    to continue on a version mismatch, referencing `frankenphp_version`.

If the preflight is deleted, or the var goes missing / non-literal, this fails.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CONFIG = REPO / "default.config.yml"
WING_TASKS = REPO / "roles" / "pazny.wing" / "tasks" / "main.yml"

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text()) or {}


def test_frankenphp_version_pinned_as_semver_literal():
    cfg = _config()
    assert "frankenphp_version" in cfg, (
        "frankenphp_version missing from default.config.yml — the FrankenPHP "
        "binary version must be pinned (tested on arm64_sequoia).")
    val = cfg["frankenphp_version"]
    assert isinstance(val, str) and _SEMVER.match(val), (
        f"frankenphp_version must be a MAJOR.MINOR.PATCH string literal, "
        f"got {val!r}")


def test_frankenphp_version_is_stock_jinja_safe():
    # The raw YAML value must carry no Jinja (no `{{ }}`, no `|` filter) so it
    # cannot trip the {{ vars }} eager-resolve trap in the plugin loader.
    raw = CONFIG.read_text()
    m = re.search(r"^frankenphp_version:\s*(.+?)\s*$", raw, re.M)
    assert m, "frankenphp_version line not found in default.config.yml"
    literal = m.group(1)
    assert "{{" not in literal and "|" not in literal, (
        f"frankenphp_version must be a bare literal, not a Jinja expr: {literal!r}")


def test_wing_role_validates_frankenphp_version():
    tasks = WING_TASKS.read_text()
    # The preflight reads the running binary's version ...
    assert "--version" in tasks, (
        "pazny.wing must read `frankenphp --version` as a post-install preflight.")
    # ... and the refuse/fail path must reference the pinned var so a mismatch
    # is an actual provisioning failure (not a silent daemon segfault).
    assert "frankenphp_version" in tasks, (
        "pazny.wing version preflight must reference frankenphp_version to gate "
        "the landed binary against the pinned version.")
    assert re.search(r"ansible\.builtin\.fail", tasks), (
        "pazny.wing must `fail` on a frankenphp version mismatch.")
