"""The thalamus bearer speaks for a person on one act only: starting an agent session.

WHY (iris-agent-dendrogram, increment 2). Iris's start_agent opens a Wing session
for the person who approved it, so Wing must stamp actor_id = user:<uid> and keep
owner scoping. Wing believed X-Nos-User-* only on the face-bff bearer; giving the
thalamus a plain write token would stamp every start "thalamus" and let every login
see every run. The thalamus bearer now carries a person, but on POST
/agents/<name>/sessions alone: never on an operator verb, never on a read, and
never without a person (files/anatomy/contracts/face-wing.yml, wire).

What runs: the REAL Api presenters through Presenter::run over an in-memory SQLite
(the harness of test_face_user_owns_its_sessions.py, plus a thalamus row and the
Admin presenter). No runner starts: WING_PHP_BIN is /usr/bin/true.
"""
from __future__ import annotations

import json

from test_face_user_owns_its_sessions import (_PRESENTERS, AUTOLOAD, _agents, _php, needs_php,
                                              needs_vendor)

_TOKENS = "$cache = new Nette\\Caching\\Storages\\DevNullStorage;"
_ADMIN = ": new App\\Presenters\\Api\\AgentSessionsPresenter($sessions);"
_RUN = "  $r = $p->run(new Nette\\Application\\Request('Api:' . $c['presenter'], $c['method'], $c['params']));"


def _harness() -> str:
    """_PRESENTERS with two thalamus rows (the minted one, and one wrongly holding wing.operator) and Admin."""
    for anchor in (_TOKENS, _ADMIN, _RUN):
        assert _PRESENTERS.count(anchor) == 1, f"the borrowed harness moved: {anchor!r}"
    return (_PRESENTERS
            .replace(_TOKENS, "foreach (['thal' => 'wing.write', 'thal-op' => 'wing.operator,wing.write'] as $t => $s) {\n"
                              "  $pdo->query('INSERT INTO api_tokens', ['token' => hash('sha256', $t), 'name' => 'thalamus', 'scopes' => $s]);\n"
                              "}\n" + _TOKENS)
            .replace(_ADMIN, ": ($c['presenter'] === 'Admin'\n"
                             "      ? (new ReflectionClass(App\\Presenters\\Api\\AdminPresenter::class))->newInstanceWithoutConstructor()\n"
                             "      : new App\\Presenters\\Api\\AgentSessionsPresenter($sessions));")
            # An Admin action that got past startup reaches its unset repositories: that is "reached", not a 403.
            .replace(_RUN, "  try { " + _RUN.strip() + " } catch (Error $e) { $out[] = ['code' => 'reached', 'body' => null]; continue; }"))


def _run(tmp_path, cases: list[dict]) -> list[dict]:
    return _php(_harness(), str(AUTOLOAD), str(_agents(tmp_path)), json.dumps(cases))


def _thal(token="thal", uid="alice", groups="nos-users,nos-admins") -> dict:
    return {"token": token, "uid": uid, "groups": groups}


def _start(agent="helper", **who) -> dict:
    return {"presenter": "Agents", "method": "POST", "params": {"action": "sessions", "name": agent},
            "body": {"prompt": "hi", "parent": "thalamus:e1e1e1e1-0000-4000-8000-000000000001"}, **who}


@needs_php
@needs_vendor
def test_a_start_through_the_thalamus_is_the_persons(tmp_path):
    admin, user, closed, bare = _run(tmp_path, [
        _start(**_thal()),
        _start(**_thal(groups="nos-users")),
        _start("ops-triage", **_thal(groups="nos-users")),
        _start(token="thal"),
    ])
    assert admin["code"] == 202 and admin["body"]["actor_id"] == "user:alice", admin
    assert user["code"] == 202 and user["body"]["actor_id"] == "user:alice", user
    assert closed["code"] == 403, "below Tier 1 the person opens only metadata.end_user agents, through any bearer"
    assert bare["code"] == 401, "the thalamus bearer without a person is no one"


@needs_php
@needs_vendor
def test_the_thalamus_bearer_reaches_nothing_else(tmp_path):
    got = _run(tmp_path, [
        {"presenter": "Agents", "method": "GET", "params": {"action": "sessions", "name": "helper"}, **_thal()},
        {"presenter": "Agents", "method": "GET", "params": {"action": "default"}, **_thal()},
        {"presenter": "AgentSessions", "method": "GET", "params": {"action": "default", "uuid": "a1"}, **_thal()},
        {"presenter": "Admin", "method": "POST", "params": {"action": "halt"}, **_thal()},
        {"presenter": "Admin", "method": "POST", "params": {"action": "halt"}, **_thal(token="thal-op")},
    ])
    assert [g["code"] for g in got] == [403, 403, 403, 403, 403], got


@needs_php
@needs_vendor
def test_the_face_bff_still_reads_and_decides(tmp_path):
    """The narrowing is the thalamus's alone: face-bff keeps its reads (a guard on the guard)."""
    listed, = _run(tmp_path, [{"presenter": "Agents", "method": "GET", "params": {"action": "sessions", "name": "helper"},
                               "token": "bff-secret", "uid": "alice", "groups": "nos-users"}])
    assert listed["code"] == 200
