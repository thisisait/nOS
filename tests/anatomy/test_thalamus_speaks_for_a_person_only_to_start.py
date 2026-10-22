"""The thalamus bearer speaks for a person on one act only: starting an agent session.

WHY (iris-agent-dendrogram, increment 2). Iris's start_agent opens a Wing session
for the person who approved it, so Wing must stamp actor_id = user:<uid> and keep
owner scoping. Wing believed X-Nos-User-* only on the face-bff bearer; giving the
thalamus a plain write token would stamp every start "thalamus" and let every login
see every run. The thalamus bearer now carries a person, but on POST
/agents/<name>/sessions and on GET /agent-sessions/<uuid> alone: never on an
operator verb, never on another read, and never without a person
(files/anatomy/contracts/face-wing.yml, wire).

GATE CHANGE (iris-subagent-reports-back, 2026-10-22): the one read is the run
the person started through Iris, narrowed like the face-bff's (another's is
404). The thalamus polls it so Iris can say when the run ended and what it
reported; before, the approve was the last thing the person ever heard.

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
        {"presenter": "AgentSessions", "method": "POST", "params": {"action": "default", "uuid": "a1"}, **_thal()},
        {"presenter": "Admin", "method": "POST", "params": {"action": "halt"}, **_thal()},
        {"presenter": "Admin", "method": "POST", "params": {"action": "halt"}, **_thal(token="thal-op")},
    ])
    assert [g["code"] for g in got] == [403, 403, 403, 403, 403], got


@needs_php
@needs_vendor
def test_the_thalamus_reads_the_persons_run_and_no_other(tmp_path):
    def one(uuid, **who):
        return {"presenter": "AgentSessions", "method": "GET", "params": {"action": "default", "uuid": uuid}, **who}
    mine, theirs, bare = _run(tmp_path, [one("a1", **_thal(groups="nos-users")), one("b1", **_thal(groups="nos-users")),
                                         one("a1", token="thal")])
    assert mine["code"] == 200 and mine["body"]["session"]["actor_id"] == "user:alice", mine
    assert theirs["code"] == 404, "another's run answers like an absent one"
    assert bare["code"] == 401, "the thalamus bearer without a person is no one"


@needs_php
@needs_vendor
def test_the_face_bff_still_reads_and_decides(tmp_path):
    """The narrowing is the thalamus's alone: face-bff keeps its reads (a guard on the guard)."""
    listed, = _run(tmp_path, [{"presenter": "Agents", "method": "GET", "params": {"action": "sessions", "name": "helper"},
                               "token": "bff-secret", "uid": "alice", "groups": "nos-users"}])
    assert listed["code"] == 200


_REPO = "$p->tokenRepo = new App\\Model\\TokenRepository($db);"
_REPORT = "SURVEY-HEAD " + "a" * 5000


def _with_events() -> str:
    """_harness with an events table: a1's report, then a later event that is no report; Wing's EventRepository injected."""
    h = _harness()
    assert h.count(_REPO) == 1 and h.count(_TOKENS) == 1, "the borrowed harness moved"
    rows = [("conductor_report", "a1", {"report": _REPORT, "filed_by": "runner"}),
            ("agent_session_end", "a1", {"stop_reason": "outcome_satisfied"}),
            ("conductor_report", "b1", {"report": "bob's"})]
    seed = "$pdo->query('CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, type TEXT, actor_action_id TEXT, result_json TEXT)');\n"
    seed += "".join(f"$pdo->query('INSERT INTO events', ['ts' => 't', 'type' => '{t}', 'actor_action_id' => '{u}', "
                    f"'result_json' => {json.dumps(json.dumps(r))}]);\n" for t, u, r in rows)
    return (h.replace(_TOKENS, seed + _TOKENS)
             .replace(_REPO, _REPO + "\n  if ($p instanceof App\\Presenters\\Api\\AgentSessionsPresenter && property_exists($p, 'events')) "
                             "$p->events = new App\\Model\\EventRepository($db);"))


@needs_php
@needs_vendor
def test_a_run_read_carries_its_newest_report_capped(tmp_path):
    """The deliverable Iris hears: the newest *_report event of that run, its body at most 4 KB, never another's."""
    got, = _php(_with_events(), str(AUTOLOAD), str(_agents(tmp_path)), json.dumps(
        [{"presenter": "AgentSessions", "method": "GET", "params": {"action": "default", "uuid": "a1"},
          "token": "bff-secret", "uid": "alice", "groups": "nos-users"}]))
    rep = got["body"].get("report")
    assert rep is not None, got["body"]
    assert rep["type"] == "conductor_report" and isinstance(rep["event_id"], int), rep
    assert rep["body"] == _REPORT[:4096] and rep["chars"] == len(_REPORT), "the head, capped at 4 KB, and the whole length"
