#!/usr/bin/env python3
"""Export the Bone FastAPI OpenAPI 3.x spec to YAML.

Anatomy A5 (2026-05-04) — first half of the contracts pair.

FastAPI auto-generates the OpenAPI schema from route signatures and
docstrings. We just dump it deterministically as YAML so it can be
committed to ``files/anatomy/skills/contracts/`` and CI-drift-checked.

The Bone app's auth bootstrap is tolerant of missing env vars
(``_AUTH_READY = False`` path), so this script can run in CI without
needing Authentik / JWKS reachable.

Usage:
    python3 bin/export-openapi.py [--output PATH]

Default output: ``files/anatomy/skills/contracts/bone.openapi.yml``
relative to the repo root (assumes the script is run from the repo root
or the bone source dir).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make ``import main`` resolve to files/anatomy/bone/main.py regardless of cwd.
HERE = Path(__file__).resolve().parent
BONE_DIR = HERE.parent
sys.path.insert(0, str(BONE_DIR))

# Bone's auth.py reads these at import time. Set tolerant defaults so the
# import succeeds in a CI sandbox without Authentik. The values do not
# affect the OpenAPI schema — only runtime auth behaviour.
os.environ.setdefault("BONE_AUTH_ISSUER", "https://auth.invalid")
os.environ.setdefault("BONE_AUTH_AUDIENCE", "bone")
os.environ.setdefault("BONE_AUTH_JWKS_URL", "https://auth.invalid/.well-known/jwks.json")

import yaml  # noqa: E402

from main import app  # noqa: E402


def _repo_root() -> Path:
    # bin/ -> bone/ -> anatomy/ -> files/ -> <repo>
    return HERE.parent.parent.parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=_repo_root() / "files/anatomy/skills/contracts/bone.openapi.yml",
        help="Destination YAML file (default: contracts/bone.openapi.yml).",
    )
    args = parser.parse_args()

    spec = app.openapi()

    # Strip non-deterministic fields. FastAPI doesn't currently inject any,
    # but version bumps could; keep this stable so drift-check sees only
    # real surface changes.
    if "info" in spec and isinstance(spec["info"], dict):
        spec["info"].pop("x-generated-at", None)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Header comment is preserved as a top-level YAML comment via
    # post-processing (PyYAML doesn't emit comments).
    body = yaml.safe_dump(
        spec,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
        width=120,
    )
    header = (
        "# AUTO-GENERATED — do not edit by hand.\n"
        "# Source: files/anatomy/bone/main.py (FastAPI app.openapi()).\n"
        "# Regenerate: python3 files/anatomy/bone/bin/export-openapi.py\n"
        "# CI drift check: .github/workflows/ci.yml — contracts-drift job.\n"
        "---\n"
    )
    args.output.write_text(header + body, encoding="utf-8")
    print(f"Wrote {args.output} ({len(body):,} bytes, {len(spec.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
