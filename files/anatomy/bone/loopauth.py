"""Bone loop auth — the THIRD credential channel, for `/api/v1/loop/*`.

Bone already carries two auth channels and this is the third, for the reason
the second one exists. From auth.py:

    The `/api/v1/events` telemetry sink keeps its bare-hex HMAC contract. […]
    the callback fires inside ansible-playbook runs, where Authentik may not be
    up — making it depend on JWT would create a bootstrap dependency on the very
    stack we're observing.

The loop has identical bootstrap properties: it must answer at 03:00 during a
blank, in CI, and on a host where Authentik is down. A reader that depends on
the stack it reads is not a reader.

TWO IDENTITIES, NEVER ONE (contract §3.4). Constraint A says the proposer and
the evaluator never share an identity; this file is that sentence at the
credential level rather than in prose:

    proposer  (the model)          BONE_LOOP_PROPOSE_TOKEN  -> {read, propose}
    evaluator (Pulse / operator)   BONE_LOOP_JUDGE_TOKEN    -> {read, judge}

Both may read. Neither may do the other's job. The weakness reader needs only
`read`, so it accepts either — but the scope split is built in NOW, because
retrofitting an identity boundary after the routes exist is how the boundary
ends up decorative.

TWO RUNTIME REFUSALS, both of which are constraints made executable:

  D (no new prefix-derived credential). A token containing `_pw_` is treated as
    UNCONFIGURED, not as a valid secret. `{prefix}_pw_{service}` is
    concatenation, not derivation — the rendered value contains the master in
    clear (see tests/anatomy/test_secret_blast_radius.py). The repo gate keeps
    the declaration honest; this keeps the RUNTIME honest, which is the lesson
    that file records about itself: measure the runtime value, not the
    declaration.

  E (loopback only, and declare it). Bone binds 127.0.0.1 (bone.plist.j2) and
    is in `traefik_skip_ids`, so a remote client should be impossible. This
    checks anyway and refuses with 403, because REM-144 was precisely a service
    whose loopback bind was real and irrelevant — Traefik proxied around it.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request

#: Every scope the loop will ever mint. `judge` is unused by the reader and is
#: declared here on purpose — the boundary is cheaper to build than to retrofit.
LOOP_SCOPES = frozenset({"read", "propose", "judge"})

#: identity -> (env var holding its token, scopes it carries)
IDENTITIES: dict[str, tuple[str, frozenset[str]]] = {
    "agent:proposer": ("BONE_LOOP_PROPOSE_TOKEN", frozenset({"read", "propose"})),
    "engine:evaluator": ("BONE_LOOP_JUDGE_TOKEN", frozenset({"read", "judge"})),
}

#: Shortest token accepted. `openssl rand -hex 32` yields 64; anything under
#: this is a placeholder someone typed, not a secret something minted.
MIN_TOKEN_LEN = 32

#: The concatenation marker. See constraint D above.
DERIVED_MARKER = "_pw_"

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


@dataclass(frozen=True)
class Caller:
    """Who is asking, and what they may do. Never carries the token itself."""

    identity: str
    scopes: frozenset[str]


def _configured() -> dict[str, tuple[str, frozenset[str]]]:
    """identity -> (token, scopes) for every identity with a USABLE token.

    A token that is empty, short, or prefix-derived is not usable. It is
    dropped here rather than compared-and-rejected later, so a misconfigured
    host answers 503 ("not configured") instead of 403 ("wrong token") — the
    operator needs to know which of those two it is.
    """
    out: dict[str, tuple[str, frozenset[str]]] = {}
    for identity, (env_var, scopes) in IDENTITIES.items():
        token = os.environ.get(env_var, "").strip()
        if not token or len(token) < MIN_TOKEN_LEN:
            continue
        if DERIVED_MARKER in token:
            # Constraint D, enforced where it can actually be enforced.
            continue
        out[identity] = (token, scopes)
    return out


def scopes_for_token(token: str) -> Caller | None:
    """Resolve a bearer to a Caller, or None. Constant-time per candidate."""
    for identity, (secret, scopes) in _configured().items():
        if hmac.compare_digest(token, secret):
            return Caller(identity=identity, scopes=scopes)
    return None


def _client_host(request: Request) -> str:
    return (request.client.host if request.client else "") or ""


def require_loop_scope(scope: str):
    """FastAPI dependency: loopback + bearer + scope. Returns the Caller."""
    if scope not in LOOP_SCOPES:  # programmer error, fail at import time
        raise ValueError(f"unknown loop scope: {scope}")

    async def _dep(
        request: Request,
        authorization: str = Header(default=""),
    ) -> Caller:
        host = _client_host(request)
        if host not in LOOPBACK_HOSTS:
            raise HTTPException(
                status_code=403,
                detail="loop API is loopback-only (constraint E)",
            )

        if not _configured():
            raise HTTPException(
                status_code=503,
                detail=(
                    "loop API not configured: set BONE_LOOP_PROPOSE_TOKEN / "
                    "BONE_LOOP_JUDGE_TOKEN to a random value of at least "
                    f"{MIN_TOKEN_LEN} chars that is not '{DERIVED_MARKER}'-derived"
                ),
            )

        if not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=401,
                detail="Authorization: Bearer <token> required",
            )
        caller = scopes_for_token(authorization.split(" ", 1)[1].strip())
        if caller is None:
            raise HTTPException(status_code=403, detail="invalid loop token")
        if scope not in caller.scopes:
            raise HTTPException(
                status_code=403,
                detail=f"identity {caller.identity} lacks loop scope '{scope}'",
            )
        request.state.loop_caller = caller
        return caller

    return _dep
