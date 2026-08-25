#!/usr/bin/env python3
"""agent-token-status — can each declared agent client mint a token RIGHT NOW.

The gap this closes (found 2026-08-25): nothing on the estate compared the
credential the runtime presents against the one the identity provider holds.
The agent manifests spelled the secret one way, Authentik registered another
source, the store persisted a third name — and the only probe on the path was
a liveness GET that goes green while the token endpoint says invalid_grant.

For every `authentik_agent_clients` entry this asks the ONE question that
matters: exchange the STORED credential (`~/.nos/secrets.yml
agent_<x>_client_secret`, the exact value pulse/secrets.py resolves for the
jobs) for a token at the estate's own Authentik.

    ok       — HTTP 200; the credential the jobs will present is the one
               the provider accepts
    REFUSED  — HTTP 400/401; the two have diverged (the exact state that
               left six agents with zero sessions ever)
    ?        — no store entry / endpoint unreachable / config unresolvable —
               UNKNOWN, never green

STRICTLY A READER in the estate's sense: it changes nothing and exits 0
whatever it finds. The single POST it makes is to the OAuth token endpoint —
token issuance is how one ASKS an IdP about a credential; there is no GET
that answers it. No secret is ever printed; findings carry names and HTTP
codes only.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SECRETS = Path.home() / ".nos/secrets.yml"


def _yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        import yaml

        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def _leaf(client_secret_tmpl: str) -> str | None:
    """`{{ nos_derived_secrets.agent_x }}` -> `agent_x`, else None."""
    import re

    m = re.fullmatch(r"\{\{ nos_derived_secrets\.(\w+) \}\}",
                     str(client_secret_tmpl))
    return m.group(1) if m else None


def _token_status(url: str, client_id: str, secret: str) -> str:
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": secret,
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return "ok" if resp.status == 200 else f"? HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401):
            reason = ""
            try:
                reason = json.loads(exc.read().decode()).get("error", "")
            except Exception:
                pass
            return f"REFUSED ({exc.code}{' ' + reason if reason else ''})"
        return f"? HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError):
        return "? endpoint unreachable"


def main() -> int:
    base = _yaml(REPO / "default.config.yml")
    over = _yaml(REPO / "config.yml")
    merged = {**base, **over}
    secrets = _yaml(SECRETS)

    tenant = merged.get("tenant_domain", "dev.local")
    ak_domain = str(merged.get("authentik_domain", f"auth.{tenant}"))
    if "{{" in ak_domain:
        ak_domain = f"auth.{tenant}"
    token_url = f"https://{ak_domain}/application/o/token/"

    clients = merged.get("authentik_agent_clients") or []
    if not clients:
        print("? authentik_agent_clients absent or unreadable — "
              "nothing to verify, which is UNKNOWN, not fine")
        return 0

    print(f"token endpoint: {token_url}")
    refused = unknown = 0
    for entry in clients:
        cid = entry.get("client_id", "?")
        leaf = _leaf(entry.get("client_secret", ""))
        if leaf is None:
            print(f"  {cid:<24} ? client_secret is not a nos_derived_secrets "
                  "leaf — no store name to verify")
            unknown += 1
            continue
        store_key = f"{leaf}_client_secret"
        if store_key not in secrets:
            print(f"  {cid:<24} ? store does not persist {store_key} — the "
                  "jobs' resolver would refuse; converge writes it")
            unknown += 1
            continue
        status = _token_status(token_url, cid, str(secrets[store_key] or ""))
        print(f"  {cid:<24} {status}   (store: {store_key})")
        refused += status.startswith("REFUSED")
        unknown += status.startswith("?")

    verified = len(clients) - refused - unknown
    print(f"{verified} ok / {refused} refused / {unknown} unknown of "
          f"{len(clients)} declared agent clients")
    if refused:
        print("! a REFUSED row means the credential the estate stores is not "
              "the one Authentik holds — a converge re-renders both from the "
              "same nos_derived_secrets leaf; if it persists after a "
              "converge, the provider row itself has drifted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
