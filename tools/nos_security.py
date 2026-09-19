#!/usr/bin/env python3
"""The live security notebook is ~/.nos/security/, not the checkout.

The nightly scan writes here. tools/rem-status.py reads here. Git copies
under docs/llm/security/ are the last PROMOTION, reviewed onto a branch —
not the live notebook.

Disposition fields (resolved_by, status, …) overlay from dispositions.json.
The scanner regenerates the queue and must not own those keys
(scan-dispositions-sidecar / sec-queue-authorship).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

GIT_REL = (
    "docs/llm/security/remediation-queue.json",
    "docs/llm/security/scan-state.json",
)

DISPOSITION_KEYS = (
    "status",
    "resolved_by",
    "resolved_at",
    "resolution",
    "resolved_detail",
    "blocked_reason",
    "decision",
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


def dispositions_path() -> Path:
    return security_dir() / "dispositions.json"


def live_path(git_rel: str) -> Path:
    return security_dir() / Path(git_rel).name


def load_dispositions() -> dict[str, dict]:
    path = dispositions_path()
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "items" in raw:
        return {i["id"]: i for i in raw["items"] if isinstance(i, dict) and i.get("id")}
    if isinstance(raw, dict):
        return {k: v for k, v in raw.items() if isinstance(v, dict)}
    return {}


def apply_dispositions(items: list[dict]) -> list[dict]:
    disp = load_dispositions()
    if not disp:
        return items
    out: list[dict] = []
    for item in items:
        overlay = disp.get(str(item.get("id") or ""))
        if not overlay:
            out.append(item)
            continue
        merged = dict(item)
        for key in DISPOSITION_KEYS:
            if key in overlay and overlay[key] is not None:
                merged[key] = overlay[key]
        out.append(merged)
    return out


def load_queue_items() -> list[dict] | None:
    """Generated notebook joined with the sidecar, or None if absent."""
    path = queue_path()
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw["items"] if isinstance(raw, dict) and "items" in raw else raw
    if not isinstance(items, list):
        return None
    return apply_dispositions(items)
