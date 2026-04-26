"""Bone authentication — Track B (2026-04-26).

Two channels coexist:

1. **JWT (default).** Operational endpoints (state / migrations / upgrades /
   patches / coexistence / run-tag) require a Bearer token issued by
   Authentik via the OAuth2 client_credentials grant. The token's `scope`
   claim must include the required capability for the route.

2. **HMAC.** The `/api/v1/events` telemetry sink keeps its bare-hex HMAC
   contract. The wing_telemetry callback fires inside ansible-playbook runs,
   where Authentik may not be up — making it depend on JWT would create a
   bootstrap dependency on the very stack we're observing.

The legacy `BONE_SECRET` API-key channel is retired (decision O4,
2026-04-26). Operators upgrading from < 2026-04-26 must rerun ansible-
playbook so the new agent OIDC clients are seeded into Authentik before
hitting the API.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Iterable

import httpx
import jwt
from fastapi import Depends, HTTPException, Header, Request

LOG = logging.getLogger("bone.auth")

# ── Configuration (env-driven) ───────────────────────────────────────────────

# Issuer URL we expect on incoming tokens. Authentik (global issuer mode)
# emits `iss = https://auth.<tld>/application/o/`. The trailing slash is
# significant for jwt.decode's strict comparison.
ISSUER = os.getenv("AUTHENTIK_OIDC_ISSUER", "").rstrip("/") + "/"

# JWKS URL Bone fetches signing keys from. Authentik publishes JWKS PER
# OAuth2 provider at `<base>/application/o/<slug>/jwks/`. There's no global
# JWKS endpoint, so operators must point this at a specific provider's slug.
# Best practice when running Bone inside the infra compose stack: use the
# internal Docker DNS name + HTTP (`http://authentik-server:9000/...`) —
# no TLS overhead, no hostname resolution dance. ALL providers in our
# blueprint share the same signing key, so any provider's JWKS works for
# verifying any agent's token.
JWKS_URL = os.getenv("AUTHENTIK_JWKS_URL", "")

# How long to cache JWKS before re-fetching. Authentik rotates signing keys
# rarely; 1h gives a balance between rotation latency and request load.
JWKS_TTL_SECONDS = int(os.getenv("AUTHENTIK_JWKS_TTL_SECONDS", "3600"))

# Tolerance for clock skew between Authentik and Bone hosts.
JWT_LEEWAY_SECONDS = int(os.getenv("BONE_JWT_LEEWAY_SECONDS", "30"))

# Optional: refuse to start if no issuer is configured. Set to "0" to allow
# Bone to boot in HMAC-only mode (telemetry pipeline still works).
REQUIRE_JWT_AUTH = os.getenv("BONE_REQUIRE_JWT_AUTH", "1") == "1"


# ── JWKS cache ───────────────────────────────────────────────────────────────


class _JWKSCache:
    """Tiny in-process cache of Authentik's signing keys.

    PyJWT ships its own PyJWKClient that does this, but it caches inside the
    library's connection pool which is awkward to mock in tests. Rolling our
    own keeps the surface small and keeps `httpx` as the single HTTP client.
    """

    def __init__(self) -> None:
        self._cached_at: float = 0.0
        self._keys: dict[str, jwt.PyJWK] = {}

    def _stale(self) -> bool:
        return (time.time() - self._cached_at) > JWKS_TTL_SECONDS

    def get_key(self, kid: str) -> jwt.PyJWK:
        if not self._keys or self._stale() or kid not in self._keys:
            self._refresh()
        if kid not in self._keys:
            # Force one re-fetch on unknown KID in case of mid-cache rotation.
            self._refresh()
        if kid not in self._keys:
            raise jwt.InvalidTokenError(f"unknown kid: {kid}")
        return self._keys[kid]

    def _refresh(self) -> None:
        if not JWKS_URL:
            raise RuntimeError("AUTHENTIK_JWKS_URL not configured")
        try:
            with httpx.Client(timeout=5.0, verify=True) as client:
                resp = client.get(JWKS_URL)
                resp.raise_for_status()
                jwks = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            LOG.warning("JWKS fetch failed: %s", exc)
            raise RuntimeError(f"JWKS fetch failed: {exc}") from exc
        keys: dict[str, jwt.PyJWK] = {}
        for k in jwks.get("keys", []):
            kid = k.get("kid")
            if not kid:
                continue
            try:
                keys[kid] = jwt.PyJWK(k)
            except jwt.InvalidKeyError as exc:
                LOG.warning("skipping malformed JWK kid=%s: %s", kid, exc)
        self._keys = keys
        self._cached_at = time.time()
        LOG.info("JWKS refreshed: %d signing keys", len(keys))


_jwks_cache = _JWKSCache()


# ── Token verification ───────────────────────────────────────────────────────


def verify_token(token: str, required_scopes: Iterable[str] = ()) -> dict:
    """Validate a JWT against the Authentik JWKS + scope expectations.

    Raises HTTPException(401) on signature / claim failures.
    Raises HTTPException(403) on scope mismatch.
    Returns the decoded claims dict on success.
    """
    if not ISSUER or not JWKS_URL:
        raise HTTPException(
            status_code=500,
            detail="Bone JWT auth not configured (AUTHENTIK_OIDC_ISSUER missing)",
        )

    try:
        unverified = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"invalid JWT header: {exc}") from exc
    kid = unverified.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="JWT missing 'kid' header")

    try:
        signing_key = _jwks_cache.get_key(kid)
    except (RuntimeError, jwt.InvalidTokenError) as exc:
        raise HTTPException(status_code=401, detail=f"JWKS lookup failed: {exc}") from exc

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=ISSUER,
            leeway=JWT_LEEWAY_SECONDS,
            # We don't enforce `aud` — Authentik sets it to client_id which
            # varies per agent. Issuer match + signature is the trust anchor.
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="JWT expired") from exc
    except jwt.InvalidIssuerError as exc:
        raise HTTPException(status_code=401, detail=f"JWT issuer mismatch: {exc}") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"JWT verification failed: {exc}") from exc

    if required_scopes:
        granted = set((claims.get("scope") or "").split())
        missing = [s for s in required_scopes if s not in granted]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"insufficient scope: missing {','.join(missing)}",
            )

    return claims


# ── FastAPI dependency factory ───────────────────────────────────────────────


def require_scope(*scopes: str):
    """Returns a FastAPI dependency that enforces the given OAuth2 scopes.

    Usage:
        @app.post("/api/run-tag")
        async def run_tag(tag: str, _claims=Depends(require_scope("nos:run-tag"))):
            ...
    """

    async def _dep(
        request: Request,
        authorization: str = Header(default=""),
    ) -> dict:
        if not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=401,
                detail="Authorization: Bearer <token> required",
            )
        token = authorization.split(" ", 1)[1].strip()
        claims = verify_token(token, required_scopes=scopes)
        # Stash on request state so handlers can read claims if they need to
        # (e.g. for audit logging the agent's client_id).
        request.state.jwt_claims = claims
        return claims

    return _dep


# ── Boot-time guard ──────────────────────────────────────────────────────────


def assert_configured() -> None:
    """Raise at module import time if JWT auth is required but not configured.

    main.py calls this so a misconfigured deployment crashes loudly at boot
    rather than silently 500-ing every request.
    """
    if not REQUIRE_JWT_AUTH:
        LOG.info("JWT auth disabled (BONE_REQUIRE_JWT_AUTH=0). HMAC-only mode.")
        return
    if not ISSUER or ISSUER == "/":
        raise RuntimeError(
            "AUTHENTIK_OIDC_ISSUER is required when BONE_REQUIRE_JWT_AUTH=1. "
            "Set it to your Authentik global-issuer URL "
            "(e.g. https://auth.dev.local/application/o/) or set "
            "BONE_REQUIRE_JWT_AUTH=0 to run HMAC-only."
        )
    if not JWKS_URL:
        raise RuntimeError(
            "AUTHENTIK_JWKS_URL could not be derived; set it explicitly."
        )
    LOG.info("JWT auth configured: issuer=%s jwks=%s", ISSUER, JWKS_URL)
