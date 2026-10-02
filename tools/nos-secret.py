#!/usr/bin/env python3
"""nos-secret — the operator's reader for the derived credential map (P1).

Two verbs, deliberately small:

  tools/nos-secret.py --status        the resolved scheme + registry size —
                                      NAMES AND STATES ONLY, never a value.
                                      This is the inertness reader: a pre-P1
                                      converged host answers
                                      "v1 (implicit — no marker recorded)".
  tools/nos-secret.py <key>           print ONE credential value to stdout.
                                      v2 only: under v1 the value embeds the
                                      operator's prefix, and putting the
                                      master into a terminal is the incident
                                      class this whole plan exists to close —
                                      the tool REFUSES and says why.
  tools/nos-secret.py --user <username> <service> <purpose>
                                      print ONE per-user leaf (§P1b), e.g.
                                      `--user pazny bsky password` — the PDS
                                      account password the bridge provisioned.
                                      v2 only, same refusal under v1.

  tools/nos-secret.py --accounts      every service login: the user name and
                                      the key to read its password with —
                                      NAMES ONLY, never a value.

Post-blank UX (docs/secrets-p1-hkdf.md §10): credentials are 43-char random
strings; this is where the operator reads e.g. their akadmin login:
`tools/nos-secret.py authentik_admin` (the leaf akadmin boots with).

STRICTLY A READER of ~/.nos/secrets.yml + the committed registry. It writes
nothing and derives locally — the master never leaves this host.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))

import nos_secret_derive as derive  # noqa: E402

STORE = Path.home() / ".nos" / "secrets.yml"
REGISTRY = REPO / "files/anatomy/secrets/registry.yml"


def _store() -> dict:
    if not STORE.is_file():
        return {}
    import yaml

    data = yaml.safe_load(STORE.read_text()) or {}
    return data if isinstance(data, dict) else {}


LOGIN_SUFFIXES = ("_admin_email", "_admin_user", "_admin_username", "_admin_login", "_user")


def accounts() -> int:
    """Which login goes with which key. Login names come from the RESOLVED config
    (config.yml over the defaults, the way tools/e2e-plan.py renders it): the
    n8n owner signs in with config.yml's n8n_admin_email, not admin@ (2026-10-02)."""
    import importlib.util
    import re
    spec = importlib.util.spec_from_file_location("e2e_plan", REPO / "tools/e2e-plan.py")
    plan = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plan)
    import getpass
    import yaml
    creds = yaml.safe_load((REPO / "default.credentials.yml").read_text()) or {}
    v = {**plan._role_defaults(), **creds, **plan.smoke.load_vars()}
    v.setdefault("ansible_facts", {"user_id": getpass.getuser()})   # nos_primary_admin's source
    env = plan._env(v)
    password_vars = {}   # registry key -> the config var that carries it
    for k, val in v.items():
        m = re.search(r"nos_derived_secrets\.(\w+)", str(val)) if isinstance(val, str) else None
        if m and ("password" in k or k.endswith("_pw")):
            password_vars.setdefault(m.group(1), k)
    rows = []
    for key, var in sorted(password_vars.items()):
        stem = var.rsplit("_password", 1)[0]
        cands = [stem + s for s in ("_email", "_user", "_username", "_login")] + \
                [stem.removesuffix("_admin") + s for s in LOGIN_SUFFIXES]
        login = next((plan._render(env, v[c]) for c in cands if c in v and c != var), "")
        rows.append((stem, str(login) or "(see the service)", key))
    for i in v.get("nos_identities") or []:
        if "authentik" in (i.get("realms") or []):
            m = re.search(r"nos_derived_secrets\.(\w+)", str(v.get(i.get("password_var"), "")))
            rows.append(("authentik", plan._render(env, i["name"]), m.group(1) if m else i.get("password_var")))
    for p in v.get("nos_extra_identities") or []:
        rows.append(("authentik", p["name"], f"--user {p['name']} nos-identity password"))
    w = max(len(r[0]) for r in rows)
    print(f"{'service'.ljust(w)}  login  →  tools/nos-secret.py <key>")
    for svc, login, key in rows:
        print(f"{svc.ljust(w)}  {login}  →  {key}")
    return 0


def main(argv: list[str]) -> int:
    user_mode = bool(argv) and argv[0] == "--user"
    if user_mode:
        if len(argv) != 4:
            print(__doc__.strip(), file=sys.stderr)
            return 2
    elif argv == ["--accounts"]:
        return accounts()
    elif len(argv) != 1 or argv[0] in ("-h", "--help"):
        print(__doc__.strip(), file=sys.stderr)
        return 2

    registry = derive.load_registry(str(REGISTRY))
    store = _store()
    recorded = str(store.get("nos_secret_scheme", "") or "")
    master = str(store.get("nos_secret_master", "") or "")

    if not STORE.is_file():
        scheme, detail = "?", "no ~/.nos/secrets.yml — never converged, or a fresh host (first converge starts v2)"
    elif recorded:
        detail = "recorded in ~/.nos/secrets.yml"
        scheme = recorded
    else:
        scheme, detail = "v1", "implicit — no marker recorded; a pre-P1 converged host"

    if argv[0] == "--status":
        print(f"secret scheme : {scheme} ({detail})")
        print(f"master        : {'present' if master else 'absent'}"
              + (" — WRONG for a v2 host" if scheme == "v2" and not master else ""))
        print(f"registry      : {len(registry)} derived credentials "
              f"({REGISTRY.relative_to(REPO)})")
        return 0

    if not user_mode:
        key = argv[0]
        if key not in registry:
            print(f"unknown credential key {key!r} — see {REGISTRY}", file=sys.stderr)
            return 2
    if scheme != "v2":
        print(
            f"refusing: the estate is on scheme {scheme}, where this value is "
            "the legacy `<prefix>_pw_…` concatenation — printing it would put "
            "the master in your terminal (the REM-144 class). You already "
            "know the v1 rule; the tool prints values only under v2.",
            file=sys.stderr,
        )
        return 1
    mb = derive.master_bytes(master)
    if user_mode:
        _, username, service, purpose = argv
        uid = derive.slugify_uid(username)
        if not uid:
            print(f"username {username!r} slugifies to nothing", file=sys.stderr)
            return 2
        print(derive.user_leaf(mb, uid, service, purpose))
        return 0
    row = registry[key]
    print(derive.estate_leaf(mb, row["service"], row["purpose"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
