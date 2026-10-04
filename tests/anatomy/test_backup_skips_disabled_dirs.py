"""Gate: a backup dir of a switched-off service is skipped, not FAILED every night.

2026-10-04: install_mikopbx false, no data dir, and dir-mikopbx failed nightly —
only gitlab had a hard-coded skip (its gate,
test_backup_skips_disabled_gitlab.py, 2026-09-14, is folded in here). Each backup_dirs_to_dump entry now names its
own install flag, and backup.sh renders only the entries whose flag is on.
"""
import pathlib
import re

import jinja2
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "roles/pazny.backup/files/backup.sh"
ALWAYS = {"tenants"}   # data of no single service


def _entries():
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity as ni
    return ni.default_config()["backup_dirs_to_dump"], ni.default_config()


def test_every_service_dir_names_an_existing_flag():
    entries, cfg = _entries()
    bad = [e["name"] for e in entries if e["name"] not in ALWAYS
           and (not e.get("flag") or e["flag"] not in cfg)]
    assert not bad, f"backup dirs without an existing install flag: {bad}"
