#!/usr/bin/env python3
"""Outline's admins are exactly Authentik's tier-1 people.

Outline takes no role from OIDC (its plugin reads OIDC_USERNAME_CLAIM, nothing
else) and makes whoever signs in first the admin: on 2026-10-01 that was the
tier-3 e2e tester, while the tier-1 tester was a member. This reads the members
of the tier-1 groups from Authentik and sets Outline's `users.role` to match:
admin for them, member for any other admin. If no tier-1 person has an Outline
account yet, nothing changes — an Outline with no admin cannot be managed.

  AUTHENTIK_TOKEN=… tools/outline-roles.py --authentik http://127.0.0.1:9000 \\
      --group nos-providers --group nos-admins [--dry-run]

Prints what changed; exit 0 also when nothing did.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

import requests

EMAIL = re.compile(r"^[^@\s,']+@[^@\s,']+$")


def tier1_emails(base: str, token: str, groups: list[str]) -> set[str]:
    out: set[str] = set()
    for g in groups:
        r = requests.get(f"{base}/api/v3/core/groups/", params={"name": g, "include_users": "true"},
                         headers={"Authorization": f"Bearer {token}"}, timeout=20)
        r.raise_for_status()
        for grp in r.json().get("results", []):
            for u in grp.get("users_obj") or []:
                mail = (u.get("email") or "").lower()
                if u.get("is_active") and EMAIL.match(mail):
                    out.add(mail)
    return out


def psql(sql: str, container: str, db: str) -> str:
    return subprocess.run(["docker", "exec", "-i", container, "psql", "-U", "postgres", "-d", db,
                           "-v", "ON_ERROR_STOP=1", "-tA"], input=sql, capture_output=True,
                          text=True, check=True).stdout


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--authentik", required=True)
    ap.add_argument("--group", action="append", required=True, help="a tier-1 group (repeat)")
    ap.add_argument("--container", default="infra-postgresql-1")
    ap.add_argument("--db", default="outline")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    admins = tier1_emails(a.authentik.rstrip("/"), os.environ["AUTHENTIK_TOKEN"], a.group)
    present = set(psql("SELECT lower(email) FROM users WHERE \"deletedAt\" IS NULL;", a.container, a.db).split())
    keep = sorted(admins & present)
    if not keep:
        print("outline-roles: no tier-1 person has an Outline account yet — nothing changed")
        return 0
    lst = ",".join(f"'{m}'" for m in keep)          # each matched EMAIL: no quote, no comma
    sql = (f"BEGIN;"
           f"UPDATE users SET role='admin' WHERE lower(email) IN ({lst}) AND role<>'admin' RETURNING 'admin '||email;"
           f"UPDATE users SET role='member' WHERE role='admin' AND lower(email) NOT IN ({lst}) RETURNING 'member '||email;"
           f"{'ROLLBACK' if a.dry_run else 'COMMIT'};")
    changed = [ln for ln in psql(sql, a.container, a.db).splitlines()
               if ln.startswith(("admin ", "member "))]
    for ln in changed:
        print(f"outline-roles: {'would set' if a.dry_run else 'set'} {ln}")
    if not changed:
        print(f"outline-roles: roles already match ({len(keep)} admin)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
