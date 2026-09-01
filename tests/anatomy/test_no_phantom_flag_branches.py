"""A consumer may not branch on a flag no config layer declares.

MEASURED 2026-09-01: `install_redis` resolves in no layer (the toggle is
`redis_docker`), yet the Kuma Redis monitor and the GDPR Redis erasure row
branched on it through `| default(false)`. Both silently did nothing, exit 0.

Asserts on the PARSED artifacts — the loaded erasure map and the loaded task
files — not on their text.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

from nos_identity import resolve_flag  # noqa: E402

ERASURE = REPO / "state" / "gdpr-erasure-map.yml"
FORGET = REPO / "tasks" / "gdpr-forget.yml"
KUMA = REPO / "roles" / "pazny.uptime_kuma" / "tasks" / "monitors.yml"

#: A toggle spelling in a `when:`. `install_flag` is an attribute name
#: (`svc.install_flag`), not a variable — the manifest join gate owns those.
TOGGLE = re.compile(r"(?<![.\w])(install_[a-z0-9_]+|[a-z0-9_]+_docker)\b")


def _whens(path: Path):
    for task in yaml.safe_load(path.read_text(encoding="utf-8")):
        when = task.get("when")
        for expr in [when] if isinstance(when, str) else (when or []):
            yield task.get("name", "?"), str(expr)


def test_erasure_map_flags_are_declared():
    rows = yaml.safe_load(ERASURE.read_text(encoding="utf-8"))["services"]
    phantom = [(r["id"], r["flag"]) for r in rows
               if r["flag"] != "always" and not resolve_flag(r["flag"])]
    assert not phantom, f"erasure rows branch on undeclared flags: {phantom}"


def test_the_erasure_plan_lookup_has_no_default():
    """`lookup('vars', x, default=false)` turns undeclared into off."""
    lax = [n for n, e in _whens(FORGET)
           if "lookup('vars'" in e and "default=" in e]
    assert not lax, f"erasure plan resolves an undeclared flag to false: {lax}"


def test_kuma_monitor_conditions_name_declared_flags():
    phantom = [(n, t) for n, e in _whens(KUMA)
               for t in TOGGLE.findall(e) if not resolve_flag(t)]
    assert not phantom, f"monitors branch on undeclared flags: {phantom}"
