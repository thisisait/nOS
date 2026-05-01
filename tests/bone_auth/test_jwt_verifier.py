"""Track B JWT verifier — unit tests.

Stands up a real RS256 keypair, signs tokens, and feeds them through
auth.verify_token() with a mocked JWKS cache. We DON'T mock PyJWT itself —
the goal is to assert our wrapper's contract (issuer match, scope check,
signature failure mapping to HTTPException) end-to-end.
"""

from __future__ import annotations

import time

import pytest

# Track J Phase 5: gate on optional Track-B-only deps (PyJWT + cryptography).
# Track B's Bone JWT verifier hasn't shipped yet (commit not on master);
# these tests live here as placeholders until then. Skipping cleanly on
# missing deps lets the rest of pytest collect green.
pytest.importorskip("jwt")
pytest.importorskip("cryptography")
import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402


ISSUER = "https://auth.test.example/application/o/"


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _sign(key, claims: dict, kid: str = "test-kid") -> str:
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def _install_keys(auth_mod, key, kid: str = "test-kid"):
    """Pre-populate the JWKS cache so we don't need a live HTTP server."""
    pyjwk = jwt.PyJWK(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True) | {"kid": kid, "alg": "RS256", "use": "sig"})
    auth_mod._jwks_cache._keys = {kid: pyjwk}
    auth_mod._jwks_cache._cached_at = time.time()


# ── tests ────────────────────────────────────────────────────────────────────


def test_valid_token_passes(auth_mod):
    key = _make_keypair()
    _install_keys(auth_mod, key)
    now = int(time.time())
    token = _sign(key, {
        "iss": ISSUER,
        "sub": "nos-state-manager",
        "iat": now,
        "exp": now + 600,
        "scope": "nos:state:read nos:state:write",
    })
    claims = auth_mod.verify_token(token, required_scopes=["nos:state:read"])
    assert claims["sub"] == "nos-state-manager"


def test_missing_required_scope_returns_403(auth_mod):
    key = _make_keypair()
    _install_keys(auth_mod, key)
    now = int(time.time())
    token = _sign(key, {
        "iss": ISSUER,
        "sub": "nos-wing",
        "iat": now,
        "exp": now + 600,
        "scope": "nos:state:read",  # NO :write
    })
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        auth_mod.verify_token(token, required_scopes=["nos:state:write"])
    assert exc.value.status_code == 403
    assert "nos:state:write" in str(exc.value.detail)


def test_expired_token_returns_401(auth_mod):
    key = _make_keypair()
    _install_keys(auth_mod, key)
    now = int(time.time())
    token = _sign(key, {
        "iss": ISSUER,
        "iat": now - 3600,
        "exp": now - 60,  # expired 60s ago, beyond leeway
        "scope": "nos:state:read",
    })
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        auth_mod.verify_token(token)
    assert exc.value.status_code == 401
    assert "expired" in str(exc.value.detail).lower()


def test_wrong_issuer_returns_401(auth_mod):
    key = _make_keypair()
    _install_keys(auth_mod, key)
    now = int(time.time())
    token = _sign(key, {
        "iss": "https://auth.evil.example/application/o/",
        "iat": now,
        "exp": now + 600,
        "scope": "nos:state:read",
    })
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        auth_mod.verify_token(token)
    assert exc.value.status_code == 401


def test_unsigned_token_rejected(auth_mod):
    """An attacker-crafted alg=none token must not authenticate."""
    key = _make_keypair()
    _install_keys(auth_mod, key)
    # PyJWT refuses to encode alg=none with a key, so we craft the token
    # manually: just header.body. with no signature.
    import base64, json
    header = base64.urlsafe_b64encode(json.dumps(
        {"alg": "none", "kid": "test-kid", "typ": "JWT"}
    ).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({
        "iss": ISSUER,
        "exp": int(time.time()) + 600,
        "scope": "nos:state:read",
    }).encode()).rstrip(b"=").decode()
    bogus = f"{header}.{payload}."
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        auth_mod.verify_token(bogus)
    assert exc.value.status_code == 401


def test_unknown_kid_triggers_jwks_refresh(auth_mod, monkeypatch):
    """An unknown kid forces one JWKS refresh; if still missing → 401."""
    refreshes = {"count": 0}

    def fake_refresh(self):
        refreshes["count"] += 1
        # Never finds the kid the test demands.
        self._keys = {}
        self._cached_at = time.time()

    monkeypatch.setattr(
        type(auth_mod._jwks_cache), "_refresh", fake_refresh, raising=True
    )
    auth_mod._jwks_cache._keys = {}
    auth_mod._jwks_cache._cached_at = 0  # force initial refresh

    key = _make_keypair()
    token = _sign(key, {
        "iss": ISSUER,
        "exp": int(time.time()) + 600,
    }, kid="unknown-kid")

    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        auth_mod.verify_token(token)
    # Initial fetch + retry-on-unknown-kid = 2 refreshes minimum
    assert refreshes["count"] >= 2
