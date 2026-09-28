#!/usr/bin/env python3
"""Turn backrest's local auth ON in a daemon-owned config.json (seed-once file).

Password on stdin. Re-hashing every run would churn (bcrypt salts randomly), so
this is a no-op once the user exists. protojson OMITS `disabled: false`, so a
MISSING key means auth is on — reading it as "off" would re-hash forever.
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys


def htpasswd_bcrypt(password: str) -> str:
    exe = shutil.which("htpasswd") or shutil.which("htpasswd", path="/usr/sbin:/usr/bin")
    if not exe:
        sys.exit("htpasswd not found (macOS: /usr/sbin; Linux: apt install apache2-utils)")
    out = subprocess.run([exe, "-niBC", "10", "admin"], input=password + "\n",
                         capture_output=True, text=True, check=True).stdout
    return out.strip().split(":", 1)[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--user", default="admin")
    # Repos/plans the role would seed on a fresh install. The live file is
    # daemon-owned, so a seed-once template never reaches an existing daemon;
    # this adds each repo/plan whose id is ABSENT and touches nothing else.
    ap.add_argument("--seed", help="rendered config.json.j2 to merge absent repos/plans from")
    args = ap.parse_args()

    password = sys.stdin.read().strip()
    if not password:
        sys.exit("empty password on stdin")

    with open(args.config) as fh:
        cfg = json.load(fh)
    seeded = 0
    if args.seed:
        with open(args.seed) as fh:
            seed = json.load(fh)
        for key in ("repos", "plans"):
            have = {x.get("id") for x in cfg.get(key) or []}
            fresh = [x for x in seed.get(key) or [] if x.get("id") not in have]
            if fresh:
                cfg[key] = (cfg.get(key) or []) + fresh
                seeded += len(fresh)
    auth = cfg.get("auth") or {}
    users = auth.get("users") or []
    if not seeded and not auth.get("disabled", False) and any(u.get("name") == args.user for u in users):
        print("UNCHANGED")
        return

    if auth.get("disabled", False) or not any(u.get("name") == args.user for u in users):
        users = [u for u in users if u.get("name") != args.user]
        users.append({"name": args.user,
                      "passwordBcrypt": base64.b64encode(htpasswd_bcrypt(password).encode()).decode()})
        cfg["auth"] = {**auth, "disabled": False, "users": users}
    tmp = args.config + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cfg, fh, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, args.config)
    print("CHANGED")
    print(f"seeded={seeded}", file=sys.stderr)


if __name__ == "__main__":
    main()
