"""Anatomy CI gate — image-pin hygiene (supply-chain reproducibility).

C1 (2026-05-25) pinned every floating Docker tag in roles/pazny.*/defaults to a
fixed version. This gate stops the drift coming back: no role default may carry a
floating image tag (latest/main/master/stable/edge/nightly/develop) unless it's
in EXCEPTIONS with a documented reason. A new `<svc>_version: latest` fails here.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]

FLOATING = {"latest", "main", "master", "stable", "edge", "nightly", "develop"}
VERSION_KEY_SUFFIXES = ("_version", "_image_version", "_tag")

# (role, var) -> reason. Each is a DELIBERATE non-pin, not drift.
EXCEPTIONS = {
    ("pazny.puter", "puter_version"): "local build image nos/puter — tag tracks our build, not a registry pull",
    ("pazny.mcp_gateway", "mcp_grafana_version"): "upstream tag UNVERIFIED at C1; minor MCP sidecar — pin once confirmed",
    ("pazny.mcp_gateway", "mcpo_version"): "ghcr.io/open-webui/mcpo publishes only main/latest — no semver tag exists",
    ("pazny.paperclip", "paperclip_version"): "ghcr.io/paperclipai/paperclip publishes only latest — no fixed tag exists",
    ("pazny.freepbx", "freepbx_version"): "excluded service (abandoned image, unfixable CVEs)",
    ("pazny.spacetimedb", "spacetimedb_version"): "excluded service (BSL license)",
    ("pazny.dotfiles", "dotfiles_repo_version"): "git repo branch ref (dotfiles), not a Docker image tag",
}


def _floating_tags() -> list[tuple[str, str, str]]:
    found = []
    for f in sorted((REPO / "roles").glob("pazny.*/defaults/main.yml")):
        role = f.parent.parent.name
        try:
            m = yaml.safe_load(f.read_text()) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(m, dict):
            continue
        for k, v in m.items():
            if not isinstance(v, str) or not k.endswith(VERSION_KEY_SUFFIXES):
                continue
            if v.strip().lower() in FLOATING:
                found.append((role, k, v.strip()))
    return found


def test_no_unexpected_floating_image_tags():
    floating = _floating_tags()
    unexpected = [(r, k, v) for (r, k, v) in floating if (r, k) not in EXCEPTIONS]
    assert not unexpected, (
        "Floating image tags in role defaults (pin to a fixed version, or add to "
        f"EXCEPTIONS with a reason): {unexpected}"
    )


def test_exceptions_still_apply():
    """Keep EXCEPTIONS honest — drop an entry once its tag gets pinned, so the
    allowlist can't quietly grant a free pass to a service that's since moved on."""
    floating = {(r, k) for (r, k, _) in _floating_tags()}
    stale = [e for e in EXCEPTIONS if e not in floating]
    assert not stale, f"EXCEPTIONS entries no longer floating (remove them): {stale}"
