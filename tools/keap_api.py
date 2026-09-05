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
import os
import subprocess

KEAP_CONTAINER = "iiab-keap-1"


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
    """The full X-Authentik-* admin identity header set + the proxy secret."""
    return {
        "X-Authentik-Username": username,
        "X-Authentik-Email": email,
        "X-Authentik-Groups": groups,
        "Content-Type": content_type,
        **proxy_header(),
    }


if __name__ == "__main__":
    # Self-check: report whether the estate is enforcing, without printing the
    # secret. `--check` exits 0 if a secret resolved, 1 otherwise.
    import sys
    got = bool(proxy_secret())
    print(f"proxy-secret {'RESOLVED (len=%d)' % len(proxy_secret()) if got else 'UNSET'}")
    sys.exit(0 if got or "--check" not in sys.argv else 1)
