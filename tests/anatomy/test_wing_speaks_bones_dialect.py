"""Wing must present Bone the credential Bone actually checks.

MEASURED 2026-08-29. `/api/v1/state` — and with it every state, migration,
upgrade, patch and coexistence proxy — answered 401. Not a token that had
expired, not a scope that was too narrow: the wrong HEADER. `BoneClient::send`
sent `X-API-Key`, a channel Bone retired with decision O4 on 2026-04-26; since
then every operational route depends on `require_scope(...)`, whose first act
is to refuse anything not beginning `Bearer `.

Four months, because both halves were individually defensible. Bone's auth is
correct and gated. Wing's client is a small, working, well-tested class. The
join between them was asserted by nobody, and the client's own docblock still
described the retired channel as current — which is how the reader who went
looking believed the code.

`App\\Core\\AgentIdentity` had done the client_credentials dance against
Authentik since Track B and had NO caller in the tree; the `nos-wing` client
and its five read scopes were already in `authentik_agent_clients`. The fix was
a wire, not a feature. The env that identity reads had never been written
either, so this file checks both ends of it: a Bearer that cannot be minted is
the same 401 wearing a different hat.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
CLIENT = REPO / "files/anatomy/wing/app/Model/BoneClient.php"
ENV = REPO / "roles/pazny.wing/templates/wing.env.j2"
PLIST = REPO / "roles/pazny.wing/templates/wing.plist.j2"
BONE_AUTH = REPO / "files/anatomy/bone/auth.py"

IDENTITY_KEYS = ("WING_AGENT_CLIENT_ID", "WING_AGENT_CLIENT_SECRET", "WING_AGENT_SCOPES")


def test_bone_still_demands_a_bearer() -> None:
    """The premise. If Bone ever accepts a key again this file is the wrong shape."""
    src = BONE_AUTH.read_text(encoding="utf-8")
    assert 'authorization.lower().startswith("bearer ")' in src, (
        "require_scope no longer refuses non-Bearer credentials — re-derive what "
        "Wing should send before trusting the assertions below"
    )


def test_the_client_sends_a_bearer_and_no_key() -> None:
    src = CLIENT.read_text(encoding="utf-8")
    assert "'Authorization: Bearer ' . $token," in src, (
        "BoneClient does not send a Bearer, so every route behind "
        "require_scope() answers 401 — the four-month defect"
    )
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith(("*", "/*", "//")))
    assert "X-API-Key" not in code, (
        "BoneClient sends X-API-Key again. Bone retired that channel (decision "
        "O4) and reads no key at all; a request carrying one authenticates as "
        "nobody."
    )


def test_the_token_comes_from_the_identity_that_had_no_caller() -> None:
    src = CLIENT.read_text(encoding="utf-8")
    assert "AgentIdentity::fromEnv()" in src, (
        "the Bearer is not minted through AgentIdentity — if it comes from "
        "somewhere else, say where, because a second minting path is a second "
        "place the scopes can drift from authentik_agent_clients"
    )


def test_an_unmintable_identity_is_not_reported_as_a_401() -> None:
    """A 401 sends the reader to the token; a 503 naming the identity sends
    them to Authentik. The four months above were spent at the wrong end."""
    src = CLIENT.read_text(encoding="utf-8")
    assert "'error' => 'Bone identity unavailable'" in src


def test_both_env_carriers_write_what_the_identity_reads() -> None:
    """Two files carry Wing's environment — the .env FrankenPHP loads and the
    launchd plist — and a key in one is not a key in the other."""
    for carrier in (ENV, PLIST):
        text = carrier.read_text(encoding="utf-8")
        missing = [k for k in IDENTITY_KEYS if k not in text]
        assert not missing, (
            f"{carrier.relative_to(REPO)} does not write {missing}. "
            "AgentIdentity::fromEnv() falls back to an EMPTY secret, so the "
            "mint throws and the state surface is down for a reason no reader "
            "of the 401 would guess."
        )
