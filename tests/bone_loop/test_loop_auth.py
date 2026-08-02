"""The loop's credential channel: two identities, loopback only, no derived key.

Constraint A says the proposer and the evaluator never share an identity. That
is a sentence about credentials, so it is tested against credentials — not
against prose in a design doc. Constraints D and E are enforced at RUNTIME here
in addition to the repo-level gates, because the blast-radius file's own kept
lesson is that reading the declaration instead of the effect is the defect
v0.10-beta is named after.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from starlette.testclient import TestClient

from .fakes import JUDGE_TOKEN, PROPOSE_TOKEN


@pytest.fixture
def scoped_app(loopauth):
    """A throwaway app exposing one route per scope, so the scope split can be
    exercised without waiting for the routes that will hold it."""
    app = FastAPI()

    @app.get("/read")
    async def _read(_=Depends(loopauth.require_loop_scope("read"))):
        return {"ok": "read"}

    @app.get("/propose")
    async def _propose(_=Depends(loopauth.require_loop_scope("propose"))):
        return {"ok": "propose"}

    @app.get("/judge")
    async def _judge(_=Depends(loopauth.require_loop_scope("judge"))):
        return {"ok": "judge"}

    return app


@pytest.fixture
def tokens(monkeypatch):
    monkeypatch.setenv("BONE_LOOP_PROPOSE_TOKEN", PROPOSE_TOKEN)
    monkeypatch.setenv("BONE_LOOP_JUDGE_TOKEN", JUDGE_TOKEN)


def _get(app, path, token=None, client_addr=("127.0.0.1", 5000)):
    with TestClient(app, client=client_addr) as c:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return c.get(path, headers=headers)


class TestTwoIdentitiesNeverOne:
    def test_the_proposer_cannot_trigger_a_judge(self, scoped_app, tokens):
        """Constraint A at the credential level. If this ever returns 200, the
        proposer can produce the reward signal for its own next modification."""
        assert _get(scoped_app, "/judge", PROPOSE_TOKEN).status_code == 403

    def test_the_evaluator_cannot_propose(self, scoped_app, tokens):
        assert _get(scoped_app, "/propose", JUDGE_TOKEN).status_code == 403

    def test_both_may_read(self, scoped_app, tokens):
        assert _get(scoped_app, "/read", PROPOSE_TOKEN).status_code == 200
        assert _get(scoped_app, "/read", JUDGE_TOKEN).status_code == 200

    def test_each_scope_reaches_exactly_one_identity(self, scoped_app, tokens):
        assert _get(scoped_app, "/propose", PROPOSE_TOKEN).status_code == 200
        assert _get(scoped_app, "/judge", JUDGE_TOKEN).status_code == 200

    def test_the_two_tokens_are_distinct_env_vars(self, loopauth):
        env_vars = {v[0] for v in loopauth.IDENTITIES.values()}
        assert len(env_vars) == len(loopauth.IDENTITIES) == 2, (
            "one env var for both identities is one identity wearing two names"
        )

    def test_scope_resolution_never_returns_the_token(self, loopauth, tokens):
        caller = loopauth.scopes_for_token(PROPOSE_TOKEN)
        assert caller.identity == "agent:proposer"
        assert PROPOSE_TOKEN not in repr(caller)


class TestBearerHandling:
    def test_no_header_is_401(self, scoped_app, tokens):
        assert _get(scoped_app, "/read").status_code == 401

    def test_wrong_token_is_403(self, scoped_app, tokens):
        assert _get(scoped_app, "/read", "x" * 64).status_code == 403

    def test_no_token_configured_is_503_not_403(self, scoped_app, monkeypatch):
        """503 and 403 mean different things to an operator: 'you wired nothing'
        versus 'you wired the wrong thing'."""
        monkeypatch.delenv("BONE_LOOP_PROPOSE_TOKEN", raising=False)
        monkeypatch.delenv("BONE_LOOP_JUDGE_TOKEN", raising=False)
        r = _get(scoped_app, "/read", PROPOSE_TOKEN)
        assert r.status_code == 503
        assert "not configured" in r.json()["detail"]


class TestConstraintD:
    def test_a_prefix_derived_token_is_refused_at_runtime(self, scoped_app, monkeypatch):
        """`{prefix}_pw_{svc}` is concatenation, not derivation: the rendered
        value contains the master in clear, so one leak yields the set. The repo
        gate keeps the declaration honest; this keeps the RUNTIME honest."""
        monkeypatch.setenv("BONE_LOOP_PROPOSE_TOKEN", "changeme_pw_loop_propose_padding_xxxx")
        monkeypatch.delenv("BONE_LOOP_JUDGE_TOKEN", raising=False)

        r = _get(scoped_app, "/read", "changeme_pw_loop_propose_padding_xxxx")
        assert r.status_code == 503, "a derived token must not authenticate anything"

    def test_a_short_token_is_refused(self, scoped_app, monkeypatch):
        monkeypatch.setenv("BONE_LOOP_PROPOSE_TOKEN", "short")
        monkeypatch.delenv("BONE_LOOP_JUDGE_TOKEN", raising=False)
        assert _get(scoped_app, "/read", "short").status_code == 503


class TestConstraintE:
    def test_a_non_loopback_client_is_refused(self, scoped_app, tokens):
        """REM-144 was a service whose loopback bind was real and IRRELEVANT —
        Traefik proxied around it via the host gateway. Bind AND check."""
        r = _get(scoped_app, "/read", PROPOSE_TOKEN, client_addr=("192.168.1.50", 4000))
        assert r.status_code == 403
        assert "loopback" in r.json()["detail"]

    def test_loopback_v4_and_v6_are_allowed(self, scoped_app, tokens):
        for addr in ("127.0.0.1", "::1"):
            assert _get(scoped_app, "/read", PROPOSE_TOKEN, (addr, 4000)).status_code == 200

    def test_the_loopback_check_runs_before_the_bearer_check(self, scoped_app, tokens):
        """A remote caller must not be able to probe token validity."""
        r = _get(scoped_app, "/read", "x" * 64, client_addr=("10.0.0.9", 4000))
        assert r.status_code == 403
        assert "loopback" in r.json()["detail"]


def test_unknown_scope_fails_at_wiring_time(loopauth):
    with pytest.raises(ValueError, match="unknown loop scope"):
        loopauth.require_loop_scope("admin")
