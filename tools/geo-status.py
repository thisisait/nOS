#!/usr/bin/env python3
"""READER: what the geo database actually holds — rows per layer, read back from PostGIS.

Counts each table itself (never trusts the loader's log for the number) and
shows the last load_log entry beside it. Exits 0 whatever it finds; an
unreachable container or a missing table is UNKNOWN / MISSING, never green.

  tools/geo-status.py [--json] [--container infra-postgresql-1] [--db geo]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

LAYERS = ("ruian_adm", "inspire_cp", "inspire_bu", "party_site")


def _psql(container: str, db: str, sql: str) -> str | None:
    try:
        r = subprocess.run(["docker", "exec", container, "psql", "-U", "postgres", "-d", db, "-tA", "-c", sql],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def read(container: str, db: str) -> dict:
    if _psql(container, db, "SELECT 1") != "1":
        return {"status": "UNKNOWN", "why": f"{container}/{db} not readable", "layers": {}}
    layers = {}
    for t in LAYERS:
        n = _psql(container, db, f"SELECT count(*) FROM geo.{t}")
        last = _psql(container, db, f"SELECT loaded_at || ' files=' || files FROM geo.load_log "
                                    f"WHERE layer = '{t}' ORDER BY loaded_at DESC LIMIT 1")
        layers[t] = {"rows": int(n) if n is not None and n.isdigit() else None, "last_load": last or None}
    empty = [t for t, v in layers.items() if not v["rows"]]
    return {"status": "OK" if not empty else "MISSING", "missing_or_empty": empty, "layers": layers}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--container", default="infra-postgresql-1")
    ap.add_argument("--db", default="geo")
    a = ap.parse_args()
    out = read(a.container, a.db)
    if a.json:
        print(json.dumps(out, indent=1))
        return 0
    print(f"geo: {out['status']}" + (f" ({out['why']})" if "why" in out else ""))
    for t, v in out["layers"].items():
        rows = "MISSING" if v["rows"] is None else v["rows"]
        print(f"  {t:<12} {rows!s:>10}   {v['last_load'] or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
