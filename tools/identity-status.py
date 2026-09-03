#!/usr/bin/env python3
"""identity-status — the declared account roster vs what each realm holds.

Reads three DECLARED sources and asks three REALMS, then prints where they
disagree. Presence is not validity (the estate's recurring lesson): a
declared identity is checked against the realm, an account the realm holds
that nobody declared is reported as UNDECLARED, and a realm that cannot be
asked is UNKNOWN — never green.

Declared sources (the repo):
  • nos_identities        default.config.yml (+ config.yml override) — humans
                          and service accounts, per-realm membership
  • authentik_agent_clients — machine OIDC clients (counted, not re-typed)
  • Bone loopauth.IDENTITIES — the loop's token identities (counted)

Realms asked (the estate, loopback only, GET only):
  • Authentik  /api/v3/core/users/          (bearer: authentik_bootstrap_token)
  • Gitea      /api/v1/admin/users          (token: gitea_api_token)
  • Woodpecker /api/users + /api/agents     (bearer: woodpecker_api_token)
  • Wing       api_tokens (sqlite, read-only) — the bearer rows themselves

STRICTLY A READER. It holds no write verb, changes nothing, and exits 0
whatever it finds — pinned by test_the_identity_reader_only_reads.py. The
reconciling acts (create the missing account, sweep the orphan agent row)
belong to the playbook, which is auditable; a reader that could also repair
would end up certifying its own repair.
"""

from __future__ import annotations

import getpass
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SECRETS = Path.home() / ".nos/secrets.yml"

OK, MISSING, UNDECLARED, UNKNOWN = "ok", "MISSING", "UNDECLARED", "?"
REALMS = ("authentik", "gitea", "woodpecker")


def _yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        import yaml  # PyYAML is a repo dev dependency

        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def _resolve(value: str, ctx: dict) -> str:
    """Resolve the handful of templates the registry legitimately uses.

    Full Jinja is the playbook's job; this resolves only what the roster
    needs and leaves anything else visibly unresolved rather than guessing.
    """
    try:
        import jinja2

        return jinja2.Environment(undefined=jinja2.ChainableUndefined).from_string(
            str(value)
        ).render(**ctx)
    except Exception:
        return str(value)


def declared_roster() -> tuple[list[dict], dict]:
    base = _yaml(REPO / "default.config.yml")
    # credentials.yml joins the merge for TOKEN lookup only (loop-review.py
    # precedent); config.yml wins last, as in the playbook's vars_files order.
    creds = _yaml(REPO / "credentials.yml")
    over = _yaml(REPO / "config.yml")
    merged = {**base, **creds, **over}
    ctx = {
        "ansible_facts": {"user_id": getpass.getuser()},
        "tenant_domain": merged.get("tenant_domain", "dev.local"),
        "nos_tester_username": merged.get("nos_tester_username", "nos-tester"),
    }
    ctx["default_admin_email"] = _resolve(
        merged.get("default_admin_email", ""), ctx
    )
    ctx["nos_primary_admin"] = _resolve(
        merged.get("nos_primary_admin", "{{ ansible_facts['user_id'] }}"), ctx
    )
    roster = []
    for entry in merged.get("nos_identities", []) or []:
        if isinstance(entry, dict) and entry.get("name"):
            roster.append({**entry, "name": _resolve(entry["name"], ctx)})
    return roster, merged


def _port(merged: dict, key: str, default: int) -> int:
    try:
        return int(merged.get(key, default))
    except (TypeError, ValueError):
        return default


def _get(url: str, headers: dict) -> object | None:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def realm_accounts(merged: dict, secrets: dict) -> dict[str, list[str] | None]:
    """realm -> usernames, or None when the realm cannot be asked."""
    out: dict[str, list[str] | None] = {}

    tok = secrets.get("authentik_bootstrap_token") or ""
    if tok:
        data = _get(
            f"http://127.0.0.1:{_port(merged, 'authentik_port', 9003)}"
            "/api/v3/core/users/?page_size=200",
            {"Authorization": f"Bearer {tok}"},
        )
        out["authentik"] = (
            [u.get("username", "") for u in data.get("results", [])]
            if isinstance(data, dict)
            else None
        )
    else:
        out["authentik"] = None

    tok = secrets.get("gitea_api_token") or ""
    if tok:
        data = _get(
            f"http://127.0.0.1:{_port(merged, 'gitea_port', 3003)}"
            "/api/v1/admin/users?limit=50",
            {"Authorization": f"token {tok}"},
        )
        out["gitea"] = (
            [u.get("login", "") for u in data] if isinstance(data, list) else None
        )
    else:
        out["gitea"] = None

    tok = (
        merged.get("woodpecker_api_token")
        or secrets.get("woodpecker_api_token")
        or ""
    )
    if tok and "_pw_" not in str(tok):
        base = f"http://127.0.0.1:{_port(merged, 'woodpecker_port', 8060)}"
        hdr = {"Authorization": f"Bearer {tok}"}
        data = _get(f"{base}/api/users?perPage=100", hdr)
        out["woodpecker"] = (
            [u.get("login", "") for u in data] if isinstance(data, list) else None
        )
        agents = _get(f"{base}/api/agents?perPage=100", hdr)
        out["_woodpecker_agents"] = (
            [f"id={a.get('id')} {a.get('name', '?')}" for a in agents]
            if isinstance(agents, list)
            else None
        )
    else:
        out["woodpecker"] = None
        out["_woodpecker_agents"] = None
    return out


def wing_tokens() -> tuple[list[dict] | None, str]:
    """The api_tokens rows, as the estate holds them.

    Why here: minting is declared in roles/pazny.wing/tasks/post.yml, and
    provision-token.php only UPSERTS — it never reconciles absence. So the
    2026-08-26 roster close retired scout / remediator / upgrade-advisor and
    parked curator / migration-author, and every one of their bearer rows is
    still live. NULL scopes is not "unset", it is UNRESTRICTED
    (TokenRepository::permits returns true on an empty list), so a retired
    agent's row is the widest credential in the estate.
    """
    db = Path.home() / "wing/app/data/wing.db"
    # Shared RO open — 2026-08-20 measurement, bit again 2026-09-03
    # (agent-status): bare mode=ro dies when Wing has checkpointed the WAL.
    import importlib.util
    import sqlite3

    spec = importlib.util.spec_from_file_location(
        "_ledger_open", Path(__file__).resolve().parent / "_ledger_open.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    conn, how = mod.open_ledger_ro(db)
    if conn is None:
        return None, how
    try:
        with conn:
            rows = conn.execute(
                # active=1 only: a deactivated row cannot authenticate (ruling 4 turned five
                # orphans off 2026-09-03) and listing it as UNRESTRICTED cried wolf.
                "SELECT name, scopes, last_used_at FROM api_tokens WHERE active = 1 ORDER BY name"
            ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        return None, str(e)
    return [dict(r) for r in rows], ""


def main() -> int:
    roster, merged = declared_roster()
    secrets = _yaml(SECRETS)
    realms = realm_accounts(merged, secrets)

    if not roster:
        print("? declaration  nos_identities absent or unreadable — "
              "nothing to check the realms against")
    else:
        print(f"declared identities ({len(roster)}):")
        for ident in roster:
            marks = []
            for realm in ident.get("realms", []) or []:
                if realm not in REALMS:
                    marks.append(f"{realm}={UNKNOWN} (no reader for realm)")
                    continue
                held = realms.get(realm)
                if held is None:
                    marks.append(f"{realm}={UNKNOWN} (realm unreadable)")
                elif ident["name"] in held:
                    marks.append(f"{realm}={OK}")
                else:
                    marks.append(f"{realm}={MISSING}")
            print(
                f"  {ident['name']:<24} kind={ident.get('kind', '?'):<9}"
                f" tier={ident.get('tier', '?')}  " + "  ".join(marks)
            )

    if any(
        realm == "woodpecker"
        and realms.get("woodpecker") is not None
        and i["name"] not in (realms.get("woodpecker") or [])
        for i in roster
        for realm in (i.get("realms") or [])
    ):
        print("  note: a Woodpecker user row materializes at first OAuth "
              "login — MISSING means never-logged-in OR allowlist-refused, "
              "the reader cannot tell which")

    declared_names = {i["name"] for i in roster}
    for realm in REALMS:
        held = realms.get(realm)
        if held is None:
            print(f"? {realm:<11} unreadable (no token or no answer) — "
                  "accounts UNKNOWN, not assumed fine")
            continue
        extra = sorted(set(filter(None, held)) - declared_names)
        if extra:
            print(f"! {realm:<11} {UNDECLARED}: {', '.join(extra)} — "
                  "present in the realm, absent from nos_identities")

    agents = realms.get("_woodpecker_agents")
    if agents is None:
        print("? woodpecker agent rows unreadable")
    else:
        print(f"woodpecker agent rows ({len(agents)}): " + "; ".join(agents))

    tokens, tokens_how = wing_tokens()
    if tokens is None:
        print(f"? wing api_tokens unreadable ({tokens_how}) — "
              "bearer rows UNKNOWN, not assumed clean")
    else:
        live_agents = {p.parent.name for p in
                       (REPO / "files/anatomy/agents").glob("*/agent.yml")}
        # Names that are not agent profiles at all — a daemon, the playbook's
        # own token, the cortex door. Their absence from files/anatomy/agents
        # is correct, not orphanhood.
        non_agents = {"ansible-provisioned", "cortex-executor", "openclaw"}
        print(f"wing api_tokens ({len(tokens)}):")
        for t in tokens:
            flags = []
            if not (t["scopes"] or "").strip():
                flags.append("UNRESTRICTED (NULL scopes)")
            if t["name"] not in live_agents and t["name"] not in non_agents:
                flags.append("no agent.yml — retired or parked")
            if t["last_used_at"] is None:
                flags.append("never authenticated")
            print(f"  {t['name']:<24} scopes={t['scopes'] or '(null)':<22}"
                  + ("  " + "; ".join(flags) if flags else ""))
        print("  note: deactivating a row is a WRITE and belongs to the "
              "operator — provision-token.php upserts, it never reconciles "
              "absence")

    # The machine rosters are declared elsewhere on purpose; count them so
    # this report names every identity channel, without re-typing them.
    clients = merged.get("authentik_agent_clients", []) or []
    print(f"machine identities: {len(clients)} authentik_agent_clients "
          "(declared in default.config.yml); 3 loop identities "
          "(files/anatomy/bone/loopauth.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
