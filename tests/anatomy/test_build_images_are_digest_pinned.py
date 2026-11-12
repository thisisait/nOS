"""Build and scanner base images are tag@digest; no Dockerfile FROM floats (supply chain, ssot/doctrine/gates.md §7).

2026-11-12 (row one-node-and-image-sbom): the face built FROM node:22-alpine, a floating tag that
moved with every upstream push, so a Node security release reached the estate only by luck. The
pins now live in default.config.yml (the one file the upgrade path writes) as tag AND digest, and
the Dockerfile takes them as a build arg with no default, so a build without the pin fails.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402
PINNED = re.compile(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}")


@pytest.mark.parametrize("var", ["face_node_image", "syft_image", "grype_image", "thalamus_rust_image"])
def test_the_pin_is_tag_and_digest(var):
    m = re.search(rf'^{var}:\s*"([^"]+)"', ni.default_config_text(), re.M)
    assert m, f"{var} is not declared in default.config.yml"
    assert PINNED.fullmatch(m.group(1)), f"{var} must be name:tag@sha256:<64 hex>, got {m.group(1)!r}"


def test_the_face_dockerfile_takes_the_pin_and_never_floats():
    froms = re.findall(r"^FROM\s+(\S+)", (REPO / "files/anatomy/face/Dockerfile").read_text(), re.M)
    assert froms, "the face Dockerfile has no FROM"
    floating = [f for f in froms if not f.startswith("${") and "@sha256:" not in f]
    assert not floating, f"a FROM floats on a tag (pin it through face_node_image): {floating}"
