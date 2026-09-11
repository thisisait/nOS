"""Shared KEAP /api access for host-side tools (2026-09-05).

Every host tool that talks to KEAP's human `/api/*` surface on the loopback
publish (127.0.0.1:8091) sends X-Authentik-* identity headers directly — it is
not behind Traefik. Since KEAP's SEC-02 proxy-trust landed (P1: identity headers
are trusted only when `x-keap-proxy-secret` matches `KEAP_PROXY_SHARED_SECRET`,
checked BEFORE any X-Authentik-* is read), those direct calls 401 unless they
ALSO present the secret — the same secret Traefik's keap-proxy@file injects for
browser traffic. A local admin tool is a legitimate trusted caller; it just has
to say so with the shared secret.

This module resolves that secret ONCE (the estate's shared-resolution rule — one
resolver, not a copy in thirteen tools) and hands back the header to merge in.

Source of truth is the running container's env, read the same way
`tools/roadmap-update.py` already reads KEAP_AGENT_TOKEN_RW — NOT ~/.nos/
secrets.yml, whose store persists only a fixed name-list that does not include
this secret. An env override (KEAP_PROXY_SHARED_SECRET) wins when set, for CI /
tests / a shell that already exported it. Unset everywhere ⇒ empty header, which
is exactly today's behavior against a KEAP that does not enforce it.
"""

from __future__ import annotations

import functools
import http.client
import json
import os
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request

KEAP_CONTAINER = "iiab-keap-1"

# ── the identity outpost (dtt-per-user-tables) ──────────────────────────────
# KEAP_IDENTITY_URL=http+unix://%2Frun%2Fnos-dgx%2Fkeap-identity.sock names a
# unix socket in front of KEAP that identifies the CALLER by uid (SO_PEERCRED)
# and injects the X-Authentik-* headers + the proxy secret itself. Behind it
# every human-door call is made AS the Linux user — no secret in user space,
# no forged akadmin — the same identity a browser gets through nginx + PAM.
# Without it (the operator's Mac estate) the tools keep speaking as akadmin
# with the proxy secret, exactly as before.
IDENTITY_URL = os.environ.get("KEAP_IDENTITY_URL", "").strip()


def via_identity() -> bool:
    return IDENTITY_URL.startswith("http+unix://")


def human_base() -> str:
    """Base URL for the human `/api/*` door: the outpost when configured."""
    if via_identity():
        return IDENTITY_URL.rstrip("/")
    return (os.environ.get("KEAP_API_URL") or "http://127.0.0.1:8091").rstrip("/")


def agent_base() -> str:
    """Base URL for the bearer `/agent/v1/*` door (never the outpost)."""
    return (os.environ.get("KEAP_API_URL") or "http://127.0.0.1:8091").rstrip("/")


class _UnixHTTPConnection(http.client.HTTPConnection):
    """http.client over AF_UNIX; the 'host' is the percent-encoded socket path."""

    def connect(self):
        path = urllib.parse.unquote(self.host)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if isinstance(self.timeout, (int, float)):   # else http.client's default sentinel object
            self.sock.settimeout(self.timeout)
        self.sock.connect(path)


class _UnixHTTPHandler(urllib.request.AbstractHTTPHandler):
    def _open(self, req):
        return self.do_open(_UnixHTTPConnection, req)


# urllib dispatches on "<scheme>_open"; the scheme carries a '+', so bind by name.
setattr(_UnixHTTPHandler, "http+unix_open", _UnixHTTPHandler._open)
if via_identity():
    urllib.request.install_opener(urllib.request.build_opener(_UnixHTTPHandler))


@functools.lru_cache(maxsize=1)
def proxy_secret() -> str:
    """The x-keap-proxy-secret value, or "" if the estate isn't enforcing it."""
    env = os.environ.get("KEAP_PROXY_SHARED_SECRET", "").strip()
    if env:
        return env
    try:
        out = subprocess.run(
            ["docker", "exec", KEAP_CONTAINER, "printenv", "KEAP_PROXY_SHARED_SECRET"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        return out
    except (OSError, subprocess.SubprocessError):
        return ""


def proxy_header() -> dict:
    """`{"x-keap-proxy-secret": ...}` to spread into a request's headers, or {}.

    Empty when no secret is configured, so spreading it is always safe:
        headers = {**MY_HDR, **proxy_header()}
    """
    sec = proxy_secret()
    return {"x-keap-proxy-secret": sec} if sec else {}


def human_headers(username: str = "akadmin",
                  email: str = "admin@pazny.eu",
                  groups: str = "nos-providers,nos-admins",
                  content_type: str = "application/json") -> dict:
    """The full X-Authentik-* admin identity header set + the proxy secret.

    Behind the identity outpost none of that is sent: the outpost decides who
    the caller is from the socket peer and drops any identity header anyway.
    """
    if via_identity():
        return {"Content-Type": content_type}
    return {
        "X-Authentik-Username": username,
        "X-Authentik-Email": email,
        "X-Authentik-Groups": groups,
        "Content-Type": content_type,
        **proxy_header(),
    }


@functools.lru_cache(maxsize=1)
def agent_token_rw() -> str:
    """The RW bearer for the agent door: env first, the running container second."""
    tok = os.environ.get("KEAP_AGENT_TOKEN_RW", "").strip()
    if tok:
        return tok
    try:
        return subprocess.run(
            ["docker", "exec", KEAP_CONTAINER, "printenv", "KEAP_AGENT_TOKEN_RW"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def write_row(table: str, values: dict) -> dict:
    """Upsert ONE row keyed by its slug, through whichever door fits the estate.

    - identity outpost configured → the HUMAN door as the caller
      (`POST /api/tables/<t>/rows {id: slug, values}`; KEAP merges into an
      existing row and validates the merged result). The table's owner, tier
      and grants decide — a tier-3 user writing the shared roadmap gets 403,
      which is the point.
    - otherwise → the AGENT door with the RW bearer, the estate's classic path
      (upsert keyed on `slug`, same merge semantics).
    Returns KEAP's JSON; raises RuntimeError with the door's message on failure.
    """
    slug = str(values.get("slug") or values.get("__id") or "").strip()
    if not slug:
        raise RuntimeError("write_row: the row needs a slug (its id)")
    if via_identity():
        body = {"id": slug, "values": {k: v for k, v in values.items() if k != "__id"}}
        url = f"{human_base()}/api/tables/{urllib.parse.quote(table, safe='')}/rows"
        hdr = human_headers()
    else:
        tok = agent_token_rw()
        if not tok:
            raise RuntimeError("no KEAP_AGENT_TOKEN_RW in the environment and none readable "
                               "from the container — the agent door needs the RW bearer")
        body = {k: v for k, v in values.items() if k != "__id"}
        url = f"{agent_base()}/agent/v1/tables/{urllib.parse.quote(table, safe='')}/rows"
        hdr = {"authorization": f"Bearer {tok}", "content-type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=hdr, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}") from None


if __name__ == "__main__":
    # Self-check: report whether the estate is enforcing, without printing the
    # secret. `--check` exits 0 if a secret resolved, 1 otherwise.
    import sys
    got = bool(proxy_secret())
    print(f"proxy-secret {'RESOLVED (len=%d)' % len(proxy_secret()) if got else 'UNSET'}")
    sys.exit(0 if got or "--check" not in sys.argv else 1)
