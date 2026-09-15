#!/usr/bin/env python3
"""The live security notebook is ~/.nos/security/, not the checkout.

The nightly scan writes here. tools/rem-status.py reads here. Git copies
under docs/llm/security/ are the last PROMOTION, reviewed onto a branch —
not the live notebook.
"""

from __future__ import annotations

import os
from pathlib import Path

GIT_REL = (
    "docs/llm/security/remediation-queue.json",
    "docs/llm/security/scan-state.json",
)


def security_dir() -> Path:
    raw = os.environ.get("NOS_SECURITY_DIR") or os.environ.get("VULNSCAN_SECURITY_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".nos" / "security"


def queue_path() -> Path:
    return security_dir() / "remediation-queue.json"


def state_path() -> Path:
    return security_dir() / "scan-state.json"


def live_path(git_rel: str) -> Path:
    return security_dir() / Path(git_rel).name
