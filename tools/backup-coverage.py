#!/usr/bin/env python3
"""What the backup set does NOT cover, and why — from default.config.yml only.

    tools/backup-coverage.py            # the unbacked gap list
    tools/backup-coverage.py --all      # every declared class

Reads the declaration the gate reconciles (backup_coverage); never the estate.
Exit 0 whatever it finds — this is a reader.
"""
import sys
from pathlib import Path
import yaml

cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "default.config.yml").read_text())
cov = cfg.get("backup_coverage") or {}
want = None if "--all" in sys.argv else "unbacked"
rows = sorted((e["class"], k, e["why"]) for k, e in cov.items() if want is None or e["class"] == want)
for c, k, why in rows:
    print(f"{c:9} {k:28} {why}")
print(f"\n{len(rows)} shown · backup_dirs_to_dump covers {len(cfg.get('backup_dirs_to_dump') or [])} dirs · "
      f"{sum(1 for e in cov.values() if e['class']=='unbacked')} declared unbacked")
