"""Agent identity helper — Track B (2026-04-26).

A tiny, dependency-light client_credentials helper used by callers that need
to talk to Bone with a Bearer JWT instead of the retired X-API-Key channel.

Used by:
    - library/nos_state.py (state-manager role end-of-run reporter)
    - any future Ansible module that POSTs to Bone

Tokens are cached on disk under ~/.nos/agent-tokens/<client_id>.json so
multiple ansible-playbook runs in the same TTL window don't hammer Authentik
for fresh tokens. The cache is rejected if the token is within
``REFRESH_BEFORE_EXPIRY_SECONDS`` of expiry — clock skew across hosts is
small and ansible runs rarely exceed a few minutes anyway.

This module deliberately avoids:
  - PyJWT dependency on the caller side (we don't VERIFY tokens here, we
    only fetch them — Authentik is the trust anchor, Bone is the verifier)
  - async/await (Ansible's run_module entrypoints are sync; making them
    async forces an event loop in every call site)

The only third-party import is `urllib`/`json`, which stdlib ships.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# When the cached token has fewer than this many seconds left we refresh.
# Authentik's default access token validity is 12h (Track B decision O3),
# so 60s leaves plenty of buffer for slow networks.
REFRESH_BEFORE_EXPIRY_SECONDS = 60

# Token cache directory. Created lazily; honors $NOS_AGENT_TOKEN_DIR override
# so test suites can sandbox.
TOKEN_DIR = os.environ.get(
    "NOS_AGENT_TOKEN_DIR",
    os.path.expanduser("~/.nos/agent-tokens"),
)

_LOCK = threading.Lock()


class AgentIdentityError(RuntimeError):
    """Raised when token acquisition fails for any reason."""


def _ensure_token_dir() -> None:
    if not os.path.isdir(TOKEN_DIR):
        os.makedirs(TOKEN_DIR, mode=0o700, exist_ok=True)


def _cache_path(client_id: str) -> str:
    safe = "".join(c for c in client_id if c.isalnum() or c in "-_") or "default"
    return os.path.join(TOKEN_DIR, f"{safe}.json")


def _load_cached(client_id: str) -> dict | None:
    path = _cache_path(client_id)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    expires_at = data.get("expires_at", 0)
    if expires_at - time.time() < REFRESH_BEFORE_EXPIRY_SECONDS:
        return None
    return data


def _store_cache(client_id: str, payload: dict) -> None:
    _ensure_token_dir()
    tmp = _cache_path(client_id) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.chmod(tmp, 0o600)
    os.replace(tmp, _cache_path(client_id))


def _fetch_token(token_url: str, client_id: str, client_secret: str,
                 scopes: list[str]) -> dict:
    """POST to Authentik's /token endpoint with client_credentials grant."""
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": " ".join(scopes),
    }).encode("utf-8")
    req = urllib.request.Request(
        token_url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_txt = exc.read().decode("utf-8", errors="replace")[:500]
        raise AgentIdentityError(
            f"Authentik {exc.code} on {token_url}: {body_txt}"
        ) from exc
    except urllib.error.URLError as exc:
        raise AgentIdentityError(f"Authentik unreachable: {exc.reason}") from exc

    access_token = data.get("access_token")
    if not access_token:
        raise AgentIdentityError(f"Authentik returned no access_token: {data}")
    expires_in = int(data.get("expires_in", 3600))
    return {
        "access_token": access_token,
        "token_type": data.get("token_type", "Bearer"),
        "scope": data.get("scope", " ".join(scopes)),
        "expires_at": int(time.time()) + expires_in,
    }


def get_token(token_url: str, client_id: str, client_secret: str,
              scopes: list[str]) -> str:
    """Return a valid access token for the given OIDC client.

    On cache miss / expiry, fetches a new token from Authentik. Thread-safe
    within a single Python process; cross-process safety is achieved by the
    O_TRUNC + os.replace dance in _store_cache.
    """
    if not token_url or not client_id or not client_secret:
        raise AgentIdentityError(
            "agent_identity.get_token requires token_url, client_id, client_secret"
        )
    with _LOCK:
        cached = _load_cached(client_id)
        if cached:
            return cached["access_token"]
        payload = _fetch_token(token_url, client_id, client_secret, scopes)
        _store_cache(client_id, payload)
        return payload["access_token"]


def authorization_header(token_url: str, client_id: str, client_secret: str,
                         scopes: list[str]) -> dict[str, str]:
    """Convenience: returns ``{"Authorization": "Bearer <jwt>"}``.

    Most callers want the header dict, not the raw token. Pre-formatted so
    they can update the requests/httpx headers in one line.
    """
    token = get_token(token_url, client_id, client_secret, scopes)
    return {"Authorization": f"Bearer {token}"}


def derive_token_url(authentik_domain: str) -> str:
    """Return the Authentik client_credentials token endpoint for a domain.

    Authentik exposes this URL at the global OAuth2 root (not per-application),
    matching the issuer mode we configure in 30-agent-clients.yaml.j2.
    """
    return f"https://{authentik_domain.rstrip('/')}/application/o/token/"


def invalidate(client_id: str) -> bool:
    """Delete the cached token for this client. Returns True if removed."""
    path = _cache_path(client_id)
    try:
        os.unlink(path)
        return True
    except FileNotFoundError:
        return False
