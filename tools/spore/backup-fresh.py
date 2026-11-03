#!/usr/bin/env python3
"""Print the hours since the last fully green backup, or "?<why>" when it is not one.

nos-spore.sh seals only on a fresh backup: every source in ~/.nos/backup-status.json succeeded
(an `off` service is not a failure) and the last backup-verify replay is green and <= 8 days old.
"""
import json
import os
import time

d = json.load(open(os.path.expanduser("~/.nos/backup-status.json")))
bad = [s["name"] for s in d.get("sources", []) if not s.get("success") and not s.get("off")]
v = json.load(open(os.path.expanduser("~/.nos/backup-verify.json")))
vbad = [a["name"] for a in v.get("artifacts", []) if not a.get("success")]
age_days = (time.time() - v.get("checked_at", 0)) / 86400
if bad or vbad:
    print("?failed:" + ",".join(bad + vbad))
elif age_days > 8:
    print(f"?verify {int(age_days)} d old")
else:
    print(int((time.time() - d.get("last_run", 0)) / 3600))
