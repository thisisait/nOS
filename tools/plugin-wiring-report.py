#!/usr/bin/env python3
"""Plugin wiring report — capability matrix + contract checks.

The 63 plugins under files/anatomy/plugins/ wire services into the platform
through a handful of optional manifest blocks (authentik / observability /
notification / ui-extension / compose_extension) plus lifecycle hooks. Coverage
of those blocks drifted unevenly as plugins were authored by different passes.
This tool makes the drift legible and enforces the uniform wiring contract.

What it reports:
  1. Capability matrix — per service plugin, which blocks are present
     (O observability, U ui-extension, N notification, C compose_extension,
      A authentik, B post_blank lifecycle).
  2. Gate parity — every `service` plugin must declare a gate
     (requires.feature_flag OR requires.app); a feature_flag must resolve to a
     real toggle var in default.config.yml.
  3. DAG — load_plugins.topological_order resolves with no cycles.
  4. Notification shape — blocks should use the canonical A9 severity routing
     (on_critical/on_high/on_medium/on_low/on_info), not the dead event-key
     shape whose template files don't exist on disk.

Usage:
  python3 tools/plugin-wiring-report.py            # print report, exit 0
  python3 tools/plugin-wiring-report.py --strict   # exit 1 on contract violations
  python3 tools/plugin-wiring-report.py --gaps     # only print what's missing
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "files/anatomy"))

from module_utils import load_plugins  # noqa: E402

PLUGINS_ROOT = REPO / "files/anatomy/plugins"
CANONICAL_SEVERITIES = {"on_critical", "on_high", "on_medium", "on_low", "on_info"}


def known_toggles() -> set[str]:
    """Top-level var names defined in default.config.yml (the toggle namespace).

    Strips {{ ... }} so PyYAML doesn't choke on Jinja-templated default values.
    """
    raw = (REPO / "default.config.yml").read_text(encoding="utf-8")
    raw = re.sub(r"\{\{[^}]+\}\}", "TEMPLATE", raw)
    data = yaml.safe_load(raw) or {}
    return set(data.keys())


def capabilities(m: dict) -> dict[str, bool]:
    return {
        "O": bool(m.get("observability")),
        "U": bool(m.get("ui-extension")),
        "N": bool(m.get("notification")),
        "C": bool(m.get("compose_extension")),
        "A": bool(m.get("authentik")),
        "B": "post_blank" in (m.get("lifecycle") or {}),
    }


def notification_shape(m: dict) -> str:
    """Return 'canonical' | 'legacy' | 'none' for the notification block."""
    n = m.get("notification")
    if not n:
        return "none"
    if any(k in CANONICAL_SEVERITIES for k in n):
        return "canonical"
    return "legacy"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any contract check fails")
    ap.add_argument("--gaps", action="store_true",
                    help="print only the missing-capability summary")
    args = ap.parse_args(argv)

    toggles = known_toggles()
    plugins = load_plugins.discover(PLUGINS_ROOT)
    services = [p for p in plugins if "service" in (p.manifest.get("type") or [])]

    violations: list[str] = []

    # ── DAG check ────────────────────────────────────────────────────────────
    dag_ok = True
    try:
        load_plugins.topological_order(plugins)
    except load_plugins.ValidationError as e:
        dag_ok = False
        violations.append(f"DAG: {e}")

    # ── Gate parity + notification shape ──────────────────────────────────────
    legacy_notif: list[str] = []
    for p in services:
        req = p.manifest.get("requires") or {}
        flag = req.get("feature_flag")
        app = req.get("app")
        if not flag and not app:
            violations.append(
                f"{p.name}: service plugin has no gate "
                f"(needs requires.feature_flag or requires.app)")
        elif flag and flag not in toggles:
            violations.append(
                f"{p.name}: feature_flag {flag!r} is not a toggle in "
                f"default.config.yml")
        if notification_shape(p.manifest) == "legacy":
            legacy_notif.append(p.name)

    # ── Capability tallies ────────────────────────────────────────────────────
    rows = [(p.name, capabilities(p.manifest)) for p in services]
    n = len(rows)
    labels = [("O", "observability"), ("U", "ui-extension"),
              ("N", "notification"), ("C", "compose_ext"),
              ("A", "authentik"), ("B", "post_blank")]

    if not args.gaps:
        print(f"=== Plugin wiring report — {len(plugins)} plugins "
              f"({n} service) ===\n")
        print(f"{'plugin':26s} O U N C A B   gate")
        print("-" * 56)
        for name, caps in rows:
            req = next(p.manifest.get("requires") or {}
                       for p in services if p.name == name)
            gate = req.get("feature_flag") or (f"app:{req.get('app')}"
                                               if req.get("app") else "—")
            mark = " ".join(("X" if caps[k] else ".") for k, _ in labels)
            print(f"{name:26s} {mark}   {gate}")
        print("-" * 56)

    print("\n=== Capability coverage ===")
    for k, lbl in labels:
        have = sum(1 for _, caps in rows if caps[k])
        missing = [name for name, caps in rows if not caps[k]]
        print(f"  {lbl:16s} {have:2d}/{n}  ({len(missing)} missing)")
        if args.gaps and missing:
            print(f"      {', '.join(missing)}")

    print("\n=== Contract checks ===")
    print(f"  DAG resolves           : {'OK' if dag_ok else 'FAIL'}")
    print(f"  gate parity            : "
          f"{'OK' if not any('gate' in v or 'feature_flag' in v for v in violations) else 'FAIL'}")
    print(f"  notification shape     : "
          f"{'OK' if not legacy_notif else f'{len(legacy_notif)} legacy: ' + ', '.join(legacy_notif)}")

    if violations:
        print("\n=== VIOLATIONS ===")
        for v in violations:
            print(f"  - {v}")

    if args.strict and violations:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
