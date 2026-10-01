#!/usr/bin/env python3
"""Every host directory nOS manages, with what a blank does to it and what the
backup does with it — ONE table, derived from the artifacts, never typed twice.

    tools/managed-status.py            # the table
    tools/managed-status.py --gaps     # only rows a blank keeps or a backup misses
    tools/managed-status.py --json     # {"rows": [...], "counts": {...}}

Sources (all rendered, nothing grepped):
  default.config.yml      every `*_dir` var, resolved with every install_* on
  tasks/removal-set.yml   `_blank_dirs` (level data), `_uninstall_source`
                          (level all), `_removal_keep` (declared, with why)
  default.config.yml      `backup_dirs_to_dump` + `backup_coverage`
The two gates that keep the declarations honest import this module:
tests/anatomy/test_blank_reset_data_dirs.py and test_backup_coverage_is_declared.py.
A reader: exit 0 whatever it finds.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "default.config.yml"
REMOVAL = REPO / "tasks/removal-set.yml"
DIR_VAR = re.compile(r"^([a-z0-9_]+_(?:data_dir|config_dir|cache_dir|certs_dir|books_dir|dir)):\s*(.*)$", re.M)
FAKE_HOME = "/H"


def jinja() -> jinja2.Environment:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["ternary"] = lambda c, a, b: a if c else b
    env.filters["bool"] = lambda v: str(v).lower() in ("1", "true", "yes")
    return env


def config_ctx(env) -> dict:
    """default.config.yml with every install_* ON and the Jinja resolved."""
    raw = yaml.safe_load(CONFIG.read_text()) or {}
    ctx = {k: v for k, v in raw.items() if isinstance(v, (str, int, bool))}
    ctx.update({k: True for k in ctx if k.startswith("install_")})
    ctx["ansible_facts"] = {"env": {"HOME": FAKE_HOME}, "machine": "arm64"}
    for _ in range(6):
        for k, v in list(ctx.items()):
            if isinstance(v, str) and "{{" in v:
                try:
                    ctx[k] = env.from_string(v).render(ctx)
                except Exception:  # noqa: BLE001 — an unrenderable var stays as written
                    continue
    return ctx


def dir_vars(ctx) -> dict[str, str]:
    out = {}
    for name, _ in DIR_VAR.findall(CONFIG.read_text()):
        v = ctx.get(name)
        if isinstance(v, str) and v.startswith("/") and "{{" not in v:
            out[name] = v.rstrip("/")
    return out


def covered(path: str, roots: set[str]) -> bool:
    return any(path == r or path.startswith(r + "/") for r in roots)


def removal_levels(env, ctx):
    facts = {}
    for t in yaml.safe_load(REMOVAL.read_text()) or []:
        facts.update(t.get("ansible.builtin.set_fact") or t.get("set_fact") or {})
    data = {r.rstrip("/") for r in yaml.safe_load(env.from_string(facts["_blank_dirs"]).render(ctx)) or []}
    all_ = {env.from_string(x).render(ctx).rstrip("/") for x in facts["_uninstall_source"]}
    keep = {k["var"]: k for k in facts["_removal_keep"]}
    return data, all_, keep


def backup_sets(env, ctx):
    cfg = yaml.safe_load(CONFIG.read_text())
    backed = {env.from_string(d["path"]).render(ctx).rstrip("/") for d in cfg["backup_dirs_to_dump"]}
    return backed, cfg.get("backup_coverage") or {}


def table() -> list[dict]:
    env = jinja()
    ctx = config_ctx(env)
    dirs = dir_vars(ctx)
    data, all_, keep = removal_levels(env, ctx)
    backed, cov = backup_sets(env, ctx)
    rows = []
    for var, path in sorted(dirs.items()):
        if covered(path, data):
            blank, blank_why = "data", ""
        elif var in keep:
            blank, blank_why = keep[var]["level"], keep[var]["why"]
        else:
            blank, blank_why = "UNDECLARED", "a blank keeps it and nothing says why"
        if covered(path, backed):
            backup, backup_why = "set", ""
        elif var in cov:
            backup, backup_why = cov[var]["class"], cov[var]["why"]
        else:
            backup, backup_why = "UNDECLARED", "outside the set and nothing says why"
        rows.append({"var": var, "path": path.replace(FAKE_HOME, "~"), "blank": blank,
                     "backup": backup, "why": backup_why or blank_why})
    return rows


def main() -> int:
    rows = table()
    gaps = [r for r in rows if r["blank"] != "data" or r["backup"] in ("unbacked", "UNDECLARED")]
    counts = {"dirs": len(rows), "blank_data": sum(r["blank"] == "data" for r in rows),
              "backup_set": sum(r["backup"] == "set" for r in rows),
              "unbacked": sum(r["backup"] == "unbacked" for r in rows),
              "undeclared": sum("UNDECLARED" in (r["blank"], r["backup"]) for r in rows)}
    if "--json" in sys.argv:
        json.dump({"rows": rows, "gaps": gaps, "counts": counts}, sys.stdout, indent=2)
        return 0
    for r in (gaps if "--gaps" in sys.argv else rows):
        print(f"{r['var']:28} blank={r['blank']:<10} backup={r['backup']:<9} {r['why'][:70]}")
    print("\n" + " · ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
